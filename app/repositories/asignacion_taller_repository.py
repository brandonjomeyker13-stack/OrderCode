# app/repositories/asignacion_taller_repository.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.repositories.base import BaseRepository


class AsignacionTallerRepository(BaseRepository[AsignacionTaller]):
    def __init__(self, db: Session):
        super().__init__(AsignacionTaller, db)

    def get_by_id(self, id: int, empresa_id: int) -> AsignacionTaller | None:
        stmt = (
            select(AsignacionTaller)
            .options(selectinload(AsignacionTaller.taller))
            .where(AsignacionTaller.id == id, AsignacionTaller.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[AsignacionTaller]:
        """Override: misma precarga de taller que get_by_id, para el listado."""
        stmt = (
            select(AsignacionTaller)
            .options(selectinload(AsignacionTaller.taller))
            .where(AsignacionTaller.empresa_id == empresa_id)
            .offset(offset)
            .limit(limit)
            .order_by(AsignacionTaller.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTaller]:
        stmt = (
            select(AsignacionTaller)
            .options(selectinload(AsignacionTaller.taller))
            .where(
                AsignacionTaller.lote_id == lote_id,
                AsignacionTaller.empresa_id == empresa_id,
            )
            .order_by(AsignacionTaller.fecha_asignacion.desc())
        )
        return list(self.db.execute(stmt).scalars().all())