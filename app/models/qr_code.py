# app/models/qr_code.py
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base 
from app.db.mixins import TimestampMixin


class QRCode(Base, TimestampMixin):
    """
    Tabla separada de tipos_prenda para poder revocar/regenerar un QR
    sin tocar el tipo de prenda, y para dejar la puerta abierta a QRs
    con expiración o control de acceso más fino en el futuro.
    """
    __tablename__ = "qr_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Token opaco y aleatorio (no el id secuencial) para que la URL del QR
    # no permita enumerar/adivinar otros tipos de prenda de la empresa.
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)