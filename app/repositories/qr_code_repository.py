# app/repositories/qr_code_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.qr_code import QRCode
from app.repositories.base import BaseRepository


class QRCodeRepository(BaseRepository[QRCode]):
    def __init__(self, db: Session):
        super().__init__(QRCode, db)

    def get_by_token(self, token: str, empresa_id: int) -> QRCode | None:
        stmt = select(QRCode).where(
            QRCode.token == token,
            QRCode.empresa_id == empresa_id,
            QRCode.activo.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()