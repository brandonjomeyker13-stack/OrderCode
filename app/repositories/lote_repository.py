# app/repositories/lote_repository.py
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
            .options(selectinload(Lote.tipo_producto))
            .where(Lote.id == id, Lote.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

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
            .options(selectinload(Lote.tipo_producto))
            .where(
                Lote.tipo_producto_id == tipo_producto_id,
                Lote.empresa_id == empresa_id,
                Lote.estado.in_(ESTADOS_ACTIVOS),
            )
            .order_by(Lote.fecha_registro.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def calcular_cantidad_asignada(self, lote_id: int, empresa_id: int) -> int:
        """Suma de lo ya asignado a talleres para este lote -- usado para
        saber cuánto queda disponible sin asignar."""
        stmt = select(func.coalesce(func.sum(AsignacionTaller.cantidad_asignada), 0)).where(
            AsignacionTaller.lote_id == lote_id,
            AsignacionTaller.empresa_id == empresa_id,
        )
        return self.db.execute(stmt).scalar_one()