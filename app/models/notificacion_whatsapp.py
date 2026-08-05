# app/models/notificacion_whatsapp.py
from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import EstadoNotificacion


class NotificacionWhatsapp(Base, TimestampMixin):
    """Un registro por cada intento de mandar la ficha técnica por WhatsApp
    a un taller -- permite saber qué falló y por qué, y reintentar sin
    perder el historial de intentos anteriores."""
    __tablename__ = "notificaciones_whatsapp"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asignacion_id: Mapped[int] = mapped_column(
        ForeignKey("asignaciones_taller.id", ondelete="CASCADE"), nullable=False, index=True
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
