# app/repositories/conteo_recepcion_repository.py
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.enums import EstadoConteo
from app.repositories.base import BaseRepository


class ConteoRecepcionRepository(BaseRepository[ConteoRecepcion]):
    """
    Uno solo para los dos puestos, a propósito.

    Bodega y corte leen exactamente las mismas filas con el mismo filtro de
    empresa; lo único que cambia es qué campos se publican después. Separar
    esto en dos repositorios duplicaría el SQL sin cerrar ninguna fuga -- las
    filas del ORM traen todas las columnas igual. El corte por puesto vive en
    los schemas y en los servicios, que es donde compra algo.
    """

    def __init__(self, db: Session):
        super().__init__(ConteoRecepcion, db)

    def _con_contexto(self):
        """Trae asignación, taller y lote de una vez.

        Los listados de recepción siempre necesitan las tres cosas para poder
        decir de qué producto y de qué taller se habla; sin esto, una lista de
        20 conteos dispara 60 consultas sueltas.
        """
        return selectinload(ConteoRecepcion.asignacion).options(
            selectinload(AsignacionTaller.taller),
            selectinload(AsignacionTaller.lote),
        )

    def listar_por_estado(
        self,
        empresa_id: int,
        estado: EstadoConteo,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ConteoRecepcion]:
        stmt = (
            select(ConteoRecepcion)
            .where(
                ConteoRecepcion.empresa_id == empresa_id,
                ConteoRecepcion.estado == estado,
            )
            .options(self._con_contexto())
            # Lo más viejo primero: un bulto sin confirmar bloquea el saldo del
            # taller, así que el que lleva más tiempo esperando es el urgente.
            .order_by(ConteoRecepcion.fecha.asc(), ConteoRecepcion.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def contar_por_estado(self, empresa_id: int, estado: EstadoConteo) -> int:
        stmt = (
            select(func.count())
            .select_from(ConteoRecepcion)
            .where(
                ConteoRecepcion.empresa_id == empresa_id,
                ConteoRecepcion.estado == estado,
            )
        )
        return self.db.execute(stmt).scalar_one()

    def obtener_con_contexto(self, id: int, empresa_id: int) -> ConteoRecepcion | None:
        stmt = (
            select(ConteoRecepcion)
            .where(ConteoRecepcion.id == id, ConteoRecepcion.empresa_id == empresa_id)
            .options(self._con_contexto())
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def listar_de_asignacion(
        self, asignacion_id: int, empresa_id: int
    ) -> list[ConteoRecepcion]:
        stmt = (
            select(ConteoRecepcion)
            .where(
                ConteoRecepcion.asignacion_id == asignacion_id,
                ConteoRecepcion.empresa_id == empresa_id,
            )
            .options(self._con_contexto())
            .order_by(ConteoRecepcion.fecha.asc(), ConteoRecepcion.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def contar_por_asignacion(
        self, asignacion_ids: list[int], empresa_id: int
    ) -> dict[int, int]:
        """Cuántos conteos lleva cada asignación, en UNA consulta.

        Es un conteo de eventos (cuántas veces se anotó), nunca de piezas: lo
        usa la lista de bodega para decirle si un bulto ya tuvo tandas
        anteriores, y esa lista no puede llevar cantidades.
        """
        if not asignacion_ids:
            return {}
        stmt = (
            select(ConteoRecepcion.asignacion_id, func.count())
            .where(
                ConteoRecepcion.asignacion_id.in_(asignacion_ids),
                ConteoRecepcion.empresa_id == empresa_id,
            )
            .group_by(ConteoRecepcion.asignacion_id)
        )
        return {fila[0]: fila[1] for fila in self.db.execute(stmt).all()}

    def sumar_confirmado(self, asignacion_id: int, empresa_id: int) -> int:
        """Unidades ya confirmadas para una asignación (buenas + dañadas).

        Hace falta al confirmar: lo que se valida no es este conteo solo, sino
        el acumulado, porque un taller puede entregar en varias tandas.
        """
        stmt = select(
            func.coalesce(
                func.sum(ConteoRecepcion.cantidad_buena + ConteoRecepcion.cantidad_danada), 0
            )
        ).where(
            ConteoRecepcion.asignacion_id == asignacion_id,
            ConteoRecepcion.empresa_id == empresa_id,
            ConteoRecepcion.estado == EstadoConteo.CONFIRMADO,
        )
        return self.db.execute(stmt).scalar_one()
