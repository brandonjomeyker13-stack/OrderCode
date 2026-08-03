# app/repositories/tipo_producto_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.tipo_producto import TipoProducto
from app.repositories.base import BaseRepository


class TipoProductoRepository(BaseRepository[TipoProducto]):
    def __init__(self, db: Session):
        super().__init__(TipoProducto, db)

    def get_by_id(self, id: int, empresa_id: int) -> TipoProducto | None:
        """Override: precarga el qr_code para evitar N+1 al serializar TipoProductoOut."""
        stmt = (
            select(TipoProducto)
            .options(selectinload(TipoProducto.qr_code))
            .where(TipoProducto.id == id, TipoProducto.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_qr_token(self, token: str, empresa_id: int) -> TipoProducto | None:
        """Para el flujo de escaneo de QR: token -> tipo_producto."""
        from app.models.qr_code import QRCode  # import local evita ciclo

        stmt = (
            select(TipoProducto)
            .join(QRCode, QRCode.id == TipoProducto.qr_code_id)
            .options(selectinload(TipoProducto.qr_code))
            .where(
                QRCode.token == token,
                QRCode.activo.is_(True),
                TipoProducto.empresa_id == empresa_id,
            )
        )
        return self.db.execute(stmt).scalar_one_or_none()