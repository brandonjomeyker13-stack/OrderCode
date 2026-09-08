# app/repositories/incidencia_repository.py
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.incidencia import Incidencia
from app.repositories.base import BaseRepository


class IncidenciaRepository(BaseRepository[Incidencia]):
    def __init__(self, db: Session):
        super().__init__(Incidencia, db)

    def _con_asignacion(self):
        return selectinload(Incidencia.asignacion).selectinload(AsignacionTaller.taller)

    def calcular_cantidad_afectada(self, asignacion_id: int, empresa_id: int) -> int:
        """Suma de mermas (incidencias) registradas para una asignación --
        estas unidades no vuelven al taller ni se pueden devolver."""
        stmt = select(func.coalesce(func.sum(Incidencia.cantidad_afectada), 0)).where(
            Incidencia.asignacion_id == asignacion_id,
            Incidencia.empresa_id == empresa_id,
        )
        return self.db.execute(stmt).scalar_one()

    def merma_por_asignacion(
        self, asignacion_ids: list[int], empresa_id: int
    ) -> dict[int, int]:
        """Merma de varias asignaciones en UNA sola consulta. Sin esto, un
        listado de 50 filas dispara 50 consultas extra (ver los servicios que
        arman los listados)."""
        if not asignacion_ids:
            return {}
        stmt = (
            select(
                Incidencia.asignacion_id,
                func.coalesce(func.sum(Incidencia.cantidad_afectada), 0),
            )
            .where(
                Incidencia.asignacion_id.in_(asignacion_ids),
                Incidencia.empresa_id == empresa_id,
            )
            .group_by(Incidencia.asignacion_id)
        )
        return {fila[0]: fila[1] for fila in self.db.execute(stmt).all()}

    def existen_en_lote(self, lote_id: int, empresa_id: int) -> bool:
        """¿Al lote todavía le queda alguna merma registrada? Decide si el
        lote puede salir de `en_revision_incidencia` cuando un admin corrige
        o descarta una: mientras quede una sin resolver, la marca se queda."""
        stmt = (
            select(Incidencia.id)
            .join(AsignacionTaller, AsignacionTaller.id == Incidencia.asignacion_id)
            .where(
                AsignacionTaller.lote_id == lote_id,
                Incidencia.empresa_id == empresa_id,
            )
            .limit(1)
        )
        return self.db.execute(stmt).first() is not None

    def get_by_id(self, id: int, empresa_id: int) -> Incidencia | None:
        stmt = (
            select(Incidencia)
            .options(self._con_asignacion())
            .where(Incidencia.id == id, Incidencia.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[Incidencia]:
        stmt = (
            select(Incidencia)
            .options(self._con_asignacion())
            .where(Incidencia.empresa_id == empresa_id)
            .offset(offset)
            .limit(limit)
            .order_by(Incidencia.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())