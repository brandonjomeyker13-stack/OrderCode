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