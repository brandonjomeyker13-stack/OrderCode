# app/repositories/lote_repository.py
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoLote
from app.models.lote import Lote
from app.repositories.base import BaseRepository

# Estados que se consideran "activos" para la vista del QR en tiempo real
# (excluye CERRADO_CLIENTE del filtro por defecto, tal como pide el doc).
ESTADOS_ACTIVOS = [
    EstadoLote.PENDIENTE_ASIGNACION,
    EstadoLote.ASIGNADO_A_TALLER,
    EstadoLote.ENTREGADO_PARCIAL,
    EstadoLote.ENTREGADO_COMPLETO,
    EstadoLote.EN_REVISION_INCIDENCIA,
]


class LoteRepository(BaseRepository[Lote]):
    def __init__(self, db: Session):
        super().__init__(Lote, db)

    def get_by_id(self, id: int, empresa_id: int) -> Lote | None:
        stmt = (
            select(Lote)
            .options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.corte),
            )
            .where(Lote.id == id, Lote.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[Lote]:
        stmt = (
            select(Lote)
            .options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.corte),
            )
            .where(Lote.empresa_id == empresa_id)
            .offset(offset)
            .limit(limit)
            .order_by(Lote.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def listar_activos_por_tipo_producto(
        self, tipo_producto_id: int, empresa_id: int
    ) -> list[Lote]:
        """
        La query central de la vista QR: lotes activos de un tipo de producto,
        sin traer el histórico completo (que se conserva en DB pero no se
        muestra por defecto -- requisito explícito del documento de contexto).
        """
        stmt = (
            select(Lote)
            .options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.corte),
            )
            .where(
                Lote.tipo_producto_id == tipo_producto_id,
                Lote.empresa_id == empresa_id,
                Lote.estado.in_(ESTADOS_ACTIVOS),
            )
            .order_by(Lote.fecha_registro.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_by_id_bloqueando(self, id: int, empresa_id: int) -> Lote | None:
        """Igual que get_by_id pero tomando un lock de fila (SELECT ... FOR
        UPDATE). Se usa antes de validar cuánto queda disponible: sin el lock,
        dos operarios asignando a la vez leen el mismo "disponible" y ambos
        pasan la validación, sobre-asignando el lote.

        El lock se libera al confirmar la transacción. En SQLite (tests) no
        existe FOR UPDATE y SQLAlchemy lo omite -- ahí no hace falta, porque
        la escritura ya es serializada."""
        stmt = (
            select(Lote)
            .options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.corte),
            )
            .where(Lote.id == id, Lote.empresa_id == empresa_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def asignado_por_lote(self, lote_ids: list[int], empresa_id: int) -> dict[int, int]:
        """Lo asignado de varios lotes en UNA consulta -- para los listados,
        que si no hacen una consulta por fila."""
        if not lote_ids:
            return {}
        stmt = (
            select(
                AsignacionTaller.lote_id,
                func.coalesce(func.sum(AsignacionTaller.cantidad_asignada), 0),
            )
            .where(
                AsignacionTaller.lote_id.in_(lote_ids),
                AsignacionTaller.empresa_id == empresa_id,
            )
            .group_by(AsignacionTaller.lote_id)
        )
        return {fila[0]: fila[1] for fila in self.db.execute(stmt).all()}

    def calcular_cantidad_asignada(self, lote_id: int, empresa_id: int) -> int:
        """Suma de lo ya asignado a talleres para este lote -- usado para
        saber cuánto queda disponible sin asignar."""
        stmt = select(func.coalesce(func.sum(AsignacionTaller.cantidad_asignada), 0)).where(
            AsignacionTaller.lote_id == lote_id,
            AsignacionTaller.empresa_id == empresa_id,
        )
        return self.db.execute(stmt).scalar_one()