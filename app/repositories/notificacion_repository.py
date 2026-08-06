# app/repositories/notificacion_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import CanalNotificacion, EstadoNotificacion
from app.models.notificacion import Notificacion


class NotificacionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, registro: Notificacion) -> Notificacion:
        self.db.add(registro)
        self.db.flush()
        return registro

    def ultima_por_asignacion(self, asignacion_id: int, empresa_id: int) -> Notificacion | None:
        stmt = (
            select(Notificacion)
            .where(
                Notificacion.asignacion_id == asignacion_id,
                Notificacion.empresa_id == empresa_id,
            )
            .order_by(Notificacion.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def resultado(
        self, asignacion_id: int, empresa_id: int
    ) -> tuple[bool, CanalNotificacion | None]:
        """(si se entregó, por qué canal). Vale el ÚLTIMO intento: un reenvío
        que sí funcionó debe contar aunque el primero haya fallado. El canal
        es None si nunca se logró entregar."""
        ultima = self.ultima_por_asignacion(asignacion_id, empresa_id)
        if ultima is None or ultima.estado != EstadoNotificacion.ENVIADO:
            return False, None
        return True, ultima.canal
