# app/models/notificacion.py
from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import CanalNotificacion, EstadoNotificacion


class Notificacion(Base, TimestampMixin):
    """Un registro por cada intento de mandarle la ficha técnica a un taller,
    por el canal que sea -- permite saber qué falló, por dónde salió, y
    reintentar sin perder el historial de intentos anteriores."""
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asignacion_id: Mapped[int] = mapped_column(
        ForeignKey("asignaciones_taller.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canal: Mapped[CanalNotificacion] = mapped_column(
        Enum(
            CanalNotificacion,
            name="canal_notificacion_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    estado: Mapped[EstadoNotificacion] = mapped_column(
        Enum(
            EstadoNotificacion,
            name="estado_notificacion_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
