# app/models/empresa.py
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base          # <-- corregido
from app.db.mixins import TimestampMixin


class Empresa(Base, TimestampMixin):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # FK circular resuelta con use_alter: usuarios.empresa_id apunta a esta
    # tabla, y esta columna apunta de vuelta al usuario que la creó.
    # ondelete SET NULL: si se borra el usuario creador, la empresa no se borra.
    usuario_propietario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", use_alter=True, ondelete="SET NULL"),
        nullable=True,
    )

    usuarios: Mapped[list["Usuario"]] = relationship(
        back_populates="empresa",
        foreign_keys="Usuario.empresa_id",
        cascade="all, delete-orphan",
    )