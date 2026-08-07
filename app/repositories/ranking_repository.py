# app/repositories/ranking_repository.py
"""
Agregados por taller acotados a un periodo.

Se separa de `ResumenRepository` porque responde otra pregunta: aquel dice
"cómo va la empresa ahora", este dice "qué hizo cada taller entre estas dos
fechas" -- que es la pregunta que se hace al cerrar una quincena o un mes.

Todas las consultas devuelven un diccionario {taller_id: valor} y son de
número FIJO: no crecen con la cantidad de talleres. Traerse las asignaciones
de cada taller por separado sería el N+1 clásico.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.fechas import rango_utc_entre
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.enums import EstadoAsignacion
from app.models.incidencia import Incidencia
from app.models.taller import Taller


class RankingRepository:
    def __init__(self, db: Session):
        self.db = db

    def talleres_de(self, empresa_id: int) -> list[Taller]:
        stmt = select(Taller).where(Taller.empresa_id == empresa_id).order_by(Taller.nombre)
        return list(self.db.execute(stmt).scalars())

    # --- Métricas del periodo ---

    def devuelto_por_taller(
        self, empresa_id: int, desde: date, hasta: date
    ) -> dict[int, tuple[int, int]]:
        """{taller_id: (unidades entregadas, número de entregas)} en el periodo.

        Sale de los EVENTOS de devolución, no del acumulado de la asignación:
        un taller que entregó 50 en enero y 30 en febrero debe aportar 30 al
        corte de febrero, no 80. Esta es la cifra sobre la que se paga.
        """
        inicio, fin = rango_utc_entre(desde, hasta)
        stmt = (
            select(
                AsignacionTaller.taller_id,
                func.coalesce(func.sum(Devolucion.cantidad), 0),
                func.count(Devolucion.id),
            )
            .select_from(Devolucion)
            .join(AsignacionTaller, AsignacionTaller.id == Devolucion.asignacion_id)
            .where(
                Devolucion.empresa_id == empresa_id,
                Devolucion.fecha >= inicio,
                Devolucion.fecha < fin,
            )
            .group_by(AsignacionTaller.taller_id)
        )
        return {
            taller_id: (unidades, entregas)
            for taller_id, unidades, entregas in self.db.execute(stmt)
        }

    def monto_por_taller(
        self, empresa_id: int, desde: date, hasta: date
    ) -> dict[int, tuple[Decimal, int]]:
        """{taller_id: (monto a pagar, unidades entregadas SIN tarifa)}.

        Se multiplica cantidad x precio entrega por entrega, usando el precio
        congelado en cada asignación. Sumar unidades y multiplicar al final
        daría mal apenas un taller trabaje dos productos de distinto valor.

        Las unidades sin tarifa se cuentan aparte en vez de tratarse como
        gratis: un total bajo porque falta cargar un precio se ve idéntico a
        un total bajo porque se trabajó poco, y son problemas muy distintos.
        """
        inicio, fin = rango_utc_entre(desde, hasta)
        stmt = (
            select(
                AsignacionTaller.taller_id,
                func.coalesce(
                    func.sum(
                        Devolucion.cantidad * func.coalesce(AsignacionTaller.precio_unitario, 0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (AsignacionTaller.precio_unitario.is_(None), Devolucion.cantidad),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .select_from(Devolucion)
            .join(AsignacionTaller, AsignacionTaller.id == Devolucion.asignacion_id)
            .where(
                Devolucion.empresa_id == empresa_id,
                Devolucion.fecha >= inicio,
                Devolucion.fecha < fin,
            )
            .group_by(AsignacionTaller.taller_id)
        )
        return {
            taller_id: (Decimal(str(monto)), sin_tarifa)
            for taller_id, monto, sin_tarifa in self.db.execute(stmt)
        }

    def merma_por_taller(self, empresa_id: int, desde: date, hasta: date) -> dict[int, int]:
        """`Incidencia.fecha` es un DATE, no un instante: se compara directo
        contra los días locales sin pasar por UTC."""
        stmt = (
            select(
                AsignacionTaller.taller_id,
                func.coalesce(func.sum(Incidencia.cantidad_afectada), 0),
            )
            .select_from(Incidencia)
            .join(AsignacionTaller, AsignacionTaller.id == Incidencia.asignacion_id)
            .where(
                Incidencia.empresa_id == empresa_id,
                Incidencia.fecha >= desde,
                Incidencia.fecha <= hasta,
            )
            .group_by(AsignacionTaller.taller_id)
        )
        return {taller_id: cantidad for taller_id, cantidad in self.db.execute(stmt)}

    def asignado_por_taller(self, empresa_id: int, desde: date, hasta: date) -> dict[int, int]:
        stmt = (
            select(
                AsignacionTaller.taller_id,
                func.coalesce(func.sum(AsignacionTaller.cantidad_asignada), 0),
            )
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.fecha_asignacion >= desde,
                AsignacionTaller.fecha_asignacion <= hasta,
            )
            .group_by(AsignacionTaller.taller_id)
        )
        return {taller_id: cantidad for taller_id, cantidad in self.db.execute(stmt)}

    def tiempos_de_entrega(
        self, empresa_id: int, desde: date, hasta: date
    ) -> dict[int, list[tuple[datetime, date]]]:
        """{taller_id: [(instante de la entrega, fecha en que se asignó)]}.

        Devuelve filas y no un promedio calculado en SQL a propósito: restar
        fechas es de las poquísimas cosas que Postgres y SQLite escriben
        distinto, y los tests corren sobre SQLite. El promedio se saca en
        Python (ver RankingService), donde da igual el motor. El volumen está
        acotado por el periodo pedido, no por el histórico completo.
        """
        inicio, fin = rango_utc_entre(desde, hasta)
        stmt = (
            select(
                AsignacionTaller.taller_id,
                Devolucion.fecha,
                AsignacionTaller.fecha_asignacion,
            )
            .select_from(Devolucion)
            .join(AsignacionTaller, AsignacionTaller.id == Devolucion.asignacion_id)
            .where(
                Devolucion.empresa_id == empresa_id,
                Devolucion.fecha >= inicio,
                Devolucion.fecha < fin,
            )
        )
        tiempos: dict[int, list[tuple[datetime, date]]] = {}
        for taller_id, entregada_el, asignada_el in self.db.execute(stmt):
            tiempos.setdefault(taller_id, []).append((entregada_el, asignada_el))
        return tiempos

    # --- Métrica de foto, no de periodo ---

    def pendiente_por_taller(self, empresa_id: int) -> dict[int, int]:
        """Lo que cada taller tiene en su poder AHORA MISMO.

        No lleva filtro de fechas y no debe llevarlo: "cuánto le falta por
        entregar" es un saldo actual. Acotarlo al periodo daría un número sin
        significado (parte de lo pendiente se asignó antes del corte).
        """
        merma = (
            select(
                Incidencia.asignacion_id.label("asignacion_id"),
                func.sum(Incidencia.cantidad_afectada).label("merma"),
            )
            .group_by(Incidencia.asignacion_id)
            .subquery()
        )
        stmt = (
            select(
                AsignacionTaller.taller_id,
                func.coalesce(
                    func.sum(
                        AsignacionTaller.cantidad_asignada
                        - func.coalesce(AsignacionTaller.cantidad_devuelta, 0)
                        - func.coalesce(merma.c.merma, 0)
                    ),
                    0,
                ),
            )
            .select_from(AsignacionTaller)
            .outerjoin(merma, merma.c.asignacion_id == AsignacionTaller.id)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO,
            )
            .group_by(AsignacionTaller.taller_id)
        )
        return {taller_id: cantidad for taller_id, cantidad in self.db.execute(stmt)}
