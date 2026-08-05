# app/repositories/notificacion_whatsapp_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EstadoNotificacion
from app.models.notificacion_whatsapp import NotificacionWhatsapp


class NotificacionWhatsappRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, registro: NotificacionWhatsapp) -> NotificacionWhatsapp:
        self.db.add(registro)
        self.db.flush()
        return registro

    def ultima_por_asignacion(self, asignacion_id: int, empresa_id: int) -> NotificacionWhatsapp | None:
        stmt = (
            select(NotificacionWhatsapp)
            .where(
                NotificacionWhatsapp.asignacion_id == asignacion_id,
                NotificacionWhatsapp.empresa_id == empresa_id,
            )
            .order_by(NotificacionWhatsapp.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def fue_exitosa(self, asignacion_id: int, empresa_id: int) -> bool:
        """True solo si el ÚLTIMO intento fue exitoso -- un reenvío que sí
        funcionó debe contar, aunque el primer intento haya fallado."""
        ultima = self.ultima_por_asignacion(asignacion_id, empresa_id)
        return ultima is not None and ultima.estado == EstadoNotificacion.ENVIADO
