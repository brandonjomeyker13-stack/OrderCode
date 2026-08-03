# app/services/lote_service.py
from datetime import date

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.enums import EstadoLote
from app.models.lote import Lote
from app.repositories.lote_repository import LoteRepository
from app.repositories.tipo_producto_repository import TipoProductoRepository
from app.schemas.lote import LoteConDisponibilidad, LoteCreate


class LoteService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = LoteRepository(db)
        self.tipo_producto_repo = TipoProductoRepository(db)

    def crear(self, empresa_id: int, data: LoteCreate) -> Lote:
        tipo_producto = self.tipo_producto_repo.get_by_id(data.tipo_producto_id, empresa_id)
        if tipo_producto is None:
            raise NotFoundError("Tipo de producto no encontrado")

        lote = self.repo.create(
            Lote(empresa_id=empresa_id, estado=EstadoLote.PENDIENTE_ASIGNACION, **data.model_dump())
        )
        self.db.commit()
        self.db.refresh(lote)
        return lote

    def obtener(self, id: int, empresa_id: int) -> Lote:
        lote = self.repo.get_by_id(id, empresa_id)
        if lote is None:
            raise NotFoundError("Lote no encontrado")
        return lote

    def listar_activos_por_tipo_producto(
        self, tipo_producto_id: int, empresa_id: int
    ) -> list[LoteConDisponibilidad]:
        """La query central de la vista de escaneo QR en tiempo real."""
        lotes = self.repo.listar_activos_por_tipo_producto(tipo_producto_id, empresa_id)
        resultado = []
        for lote in lotes:
            asignado = self.repo.calcular_cantidad_asignada(lote.id, empresa_id)
            columnas = {c.name: getattr(lote, c.name) for c in lote.__table__.columns}
            resultado.append(
                LoteConDisponibilidad(
                    **columnas,
                    tipo_producto=lote.tipo_producto,
                    cantidad_asignada_total=asignado,
                    cantidad_disponible=lote.cantidad_total - asignado,
                )
            )
        return resultado

    def cerrar_hacia_cliente(self, id: int, empresa_id: int, fecha_entrega: date) -> Lote:
        lote = self.obtener(id, empresa_id)
        if lote.estado != EstadoLote.ENTREGADO_COMPLETO:
            raise ValidationError(
                "Solo se puede cerrar hacia cliente un lote en estado 'entregado_completo'"
            )
        lote.estado = EstadoLote.CERRADO_CLIENTE
        lote.fecha_entrega_cliente = fecha_entrega
        self.db.commit()
        self.db.refresh(lote)
        return lote