# app/models/refresh_token.py
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base 
from app.db.mixins import TimestampMixin


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Nunca se guarda el JWT tal cual, solo el hash (SHA-256 es suficiente
    # aquí, no Argon2 -- esto no es una contraseña, es un token ya aleatorio
    # de alta entropía; hashearlo solo protege contra lectura directa de la DB).
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Cuándo se canjeó este token por uno nuevo (rotación). Se guarda en vez
    # de revocarlo de una para poder distinguir dos casos muy distintos:
    # - Reuso a los pocos segundos -> son dos pestañas refrescando a la vez,
    #   es normal y se tolera (ver REFRESH_TOKEN_GRACIA_SEGUNDOS).
    # - Reuso mucho después -> alguien se copió la cookie; ahí se cierran
    #   todas las sesiones del usuario.
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_origen: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)