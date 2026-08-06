# app/models/empresa.py
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base 
from app.db.mixins import TimestampMixin


class Empresa(Base, TimestampMixin):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    # False por defecto a propósito: toda empresa nueva (registro normal o
    # Google Sign-In) arranca pausada hasta que un admin la active a mano
    # tras confirmar el pago -- sin esto, cualquiera podía crear una cuenta
    # y usarla sin pagar, y la única defensa era desactivar después.
    activo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Derecho de supresión (Ley 1581): cuándo el cliente pidió borrar su
    # cuenta. No borra nada de inmediato -- hay un periodo de gracia en el que
    # se puede cancelar (ver EmpresaService.solicitar_eliminacion), y solo
    # después se purgan los datos de verdad.
    # Es independiente de `activo`: pedir la baja no es lo mismo que estar
    # pausado por falta de pago, y se responden con mensajes distintos.
    eliminacion_solicitada_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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