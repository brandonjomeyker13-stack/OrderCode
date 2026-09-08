# app/repositories/resumen_repository.py
"""
Consultas agregadas para los tableros. Viven aparte de los repositorios por
entidad porque cruzan varias tablas a la vez, y su razón de ser es que el
front NO tenga que traerse listados completos para sumarlos en memoria.
"""
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.fechas import rango_utc_del_dia
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.enums import EstadoAsignacion, EstadoLote
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.models.taller import Taller


class ResumenRepository:
    def __init__(self, db: Session):
        self.db = db

    def _merma_por_asignacion(self, empresa_id: int):
        """Subconsulta con la merma acumulada de cada asignación. Se usa con
        outer join para no perder las asignaciones que no tienen incidencias.

        Filtra por empresa como todo el resto (la regla de oro de
        BaseRepository): hoy los totales saldrían bien igual porque
        asignacion_id es única entre todas las empresas, pero sin el filtro
        esto agrega la tabla de incidencias de TODOS los tenants para
        responderle a uno solo."""
        return (
            select(
                Incidencia.asignacion_id.label("asignacion_id"),
                func.sum(Incidencia.cantidad_afectada).label("merma"),
            )
            .where(Incidencia.empresa_id == empresa_id)
            .group_by(Incidencia.asignacion_id)
            .subquery()
        )

    def _unidades_pendientes(self, empresa_id: int) -> Select:
        """asignado - devuelto - merma, solo de lo que sigue en poder del
        taller (las cerradas aportan cero por definición)."""
        merma = self._merma_por_asignacion(empresa_id)
        return (
            select(
                func.coalesce(
                    func.sum(
                        AsignacionTaller.cantidad_asignada
                        - func.coalesce(AsignacionTaller.cantidad_devuelta, 0)
                        - func.coalesce(merma.c.merma, 0)
                    ),
                    0,
                )
            )
            .select_from(AsignacionTaller)
            .outerjoin(merma, merma.c.asignacion_id == AsignacionTaller.id)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO,
            )
        )

    # --- Resumen general de la empresa ---

    def unidades_en_taller(self, empresa_id: int) -> int:
        return self.db.execute(self._unidades_pendientes(empresa_id)).scalar_one()

    def unidades_devueltas(self, empresa_id: int) -> int:
        stmt = select(
            func.coalesce(func.sum(AsignacionTaller.cantidad_devuelta), 0)
        ).where(AsignacionTaller.empresa_id == empresa_id)
        return self.db.execute(stmt).scalar_one()

    def unidades_devueltas_en(self, empresa_id: int, dia: date) -> int:
        """Lo que entregaron los talleres en un día concreto.

        Antes esto no se podía calcular: solo existía el acumulado por
        asignación y la fecha de la última entrega, así que un taller que
        devolvió 50 el lunes y 30 hoy aparecía como 80 devueltas hoy. Con la
        tabla de eventos sale exacto."""
        inicio, fin = rango_utc_del_dia(dia)
        stmt = select(func.coalesce(func.sum(Devolucion.cantidad), 0)).where(
            Devolucion.empresa_id == empresa_id,
            Devolucion.fecha >= inicio,
            Devolucion.fecha < fin,
        )
        return self.db.execute(stmt).scalar_one()

    def unidades_en_merma(self, empresa_id: int) -> int:
        stmt = select(func.coalesce(func.sum(Incidencia.cantidad_afectada), 0)).where(
            Incidencia.empresa_id == empresa_id
        )
        return self.db.execute(stmt).scalar_one()

    def talleres_activos(self, empresa_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Taller)
            .where(Taller.empresa_id == empresa_id, Taller.activo.is_(True))
        )
        return self.db.execute(stmt).scalar_one()

    def lotes_pendientes_de_asignar(self, empresa_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Lote)
            .where(
                Lote.empresa_id == empresa_id,
                Lote.estado == EstadoLote.PENDIENTE_ASIGNACION,
            )
        )
        return self.db.execute(stmt).scalar_one()

    def asignaciones_abiertas(self, empresa_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(AsignacionTaller)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO,
            )
        )
        return self.db.execute(stmt).scalar_one()

    # --- Resumen de un taller concreto ---

    def unidades_en_taller_de(self, empresa_id: int, taller_id: int) -> int:
        stmt = self._unidades_pendientes(empresa_id).where(
            AsignacionTaller.taller_id == taller_id
        )
        return self.db.execute(stmt).scalar_one()

    def unidades_devueltas_de(self, empresa_id: int, taller_id: int) -> int:
        stmt = select(func.coalesce(func.sum(AsignacionTaller.cantidad_devuelta), 0)).where(
            AsignacionTaller.empresa_id == empresa_id,
            AsignacionTaller.taller_id == taller_id,
        )
        return self.db.execute(stmt).scalar_one()

    def unidades_en_merma_de(self, empresa_id: int, taller_id: int) -> int:
        stmt = (
            select(func.coalesce(func.sum(Incidencia.cantidad_afectada), 0))
            .select_from(Incidencia)
            .join(AsignacionTaller, AsignacionTaller.id == Incidencia.asignacion_id)
            .where(
                Incidencia.empresa_id == empresa_id,
                AsignacionTaller.taller_id == taller_id,
            )
        )
        return self.db.execute(stmt).scalar_one()

    def conteo_asignaciones_de(
        self, empresa_id: int, taller_id: int, solo_abiertas: bool
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(AsignacionTaller)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.taller_id == taller_id,
            )
        )
        if solo_abiertas:
            stmt = stmt.where(AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO)
        return self.db.execute(stmt).scalar_one()

    def lotes_distintos_en_taller(self, empresa_id: int, taller_id: int) -> int:
        stmt = (
            select(func.count(func.distinct(AsignacionTaller.lote_id)))
            .select_from(AsignacionTaller)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.taller_id == taller_id,
                AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO,
            )
        )
        return self.db.execute(stmt).scalar_one()

    def total_incidencias_de(self, empresa_id: int, taller_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Incidencia)
            .join(AsignacionTaller, AsignacionTaller.id == Incidencia.asignacion_id)
            .where(
                Incidencia.empresa_id == empresa_id,
                AsignacionTaller.taller_id == taller_id,
            )
        )
        return self.db.execute(stmt).scalar_one()
