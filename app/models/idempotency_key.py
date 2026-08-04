# app/models/idempotency_key.py
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class IdempotencyKey(Base, TimestampMixin):
    """
    Registra qué recurso resultó de una `Idempotency-Key` ya procesada, para
    que un reintento (doble clic, retry de red) devuelva el mismo resultado
    en vez de repetir la operación. El UNIQUE constraint es lo que realmente
    evita la duplicación en una carrera entre dos requests simultáneas con
    la misma clave -- gana la primera que confirme el commit.
    """
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("empresa_id", "clave", name="uq_idempotency_key_empresa_clave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    clave: Mapped[str] = mapped_column(String(255), nullable=False)
    ruta: Mapped[str] = mapped_column(String(150), nullable=False)
    recurso_tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    recurso_id: Mapped[int] = mapped_column(Integer, nullable=False)
