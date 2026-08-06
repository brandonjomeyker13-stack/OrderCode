# app/models/taller.py
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base 
from app.db.mixins import TimestampMixin


class Taller(Base, TimestampMixin):
    __tablename__ = "talleres"
    __table_args__ = (
        UniqueConstraint("empresa_id", "numero_taller", name="uq_taller_numero_empresa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    numero_taller: Mapped[str] = mapped_column(String(30), nullable=False)
    telefono: Mapped[str] = mapped_column(String(20), nullable=False)
    # Opcional: se usa para mandarle la ficha técnica cuando WhatsApp no está
    # disponible (ver notificacion_taller_service). Muchos talleres pequeños
    # no manejan correo, por eso no es obligatorio.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)