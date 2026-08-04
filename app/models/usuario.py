# app/models/usuario.py
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import RolUsuario


class Usuario(Base, TimestampMixin):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[RolUsuario] = mapped_column(
        Enum(
            RolUsuario,
            name="rol_usuario_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=RolUsuario.OPERADOR,
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Bloqueo por fuerza bruta -- ver AuthService.autenticar. Se resetean
    # ambos en cuanto el login es exitoso.
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Google Sign-In -- ver AuthService.autenticar_con_google. email_verificado
    # se marca True al confirmar con Google (nunca con registro por password
    # solo, no hay flujo de verificación por link de correo todavía).
    email_verificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # False solo para cuentas creadas por Google Sign-In (arrancan con un
    # password_hash aleatorio e inutilizable) -- el front usa este flag para
    # mandarlas a "configura tu cuenta" antes que al dashboard normal.
    password_configurada: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    empresa: Mapped["Empresa"] = relationship(
        back_populates="usuarios", foreign_keys=[empresa_id]
    )
    