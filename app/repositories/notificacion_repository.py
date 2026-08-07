# app/repositories/notificacion_repository.py
from sqlalchemy import func, select
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

    def asignaciones_con_ultimo_envio_fallido(self, empresa_id: int) -> list[Notificacion]:
        """El último intento de cada asignación, solo donde ese último falló.

        Se mira el último y no "si alguna vez falló": una asignación que falló
        y después se reenvió bien no debe seguir apareciendo como problema."""
        ultimos = (
            select(func.max(Notificacion.id))
            .where(Notificacion.empresa_id == empresa_id)
            .group_by(Notificacion.asignacion_id)
        )
        stmt = (
            select(Notificacion)
            .where(
                Notificacion.id.in_(ultimos),
                Notificacion.estado == EstadoNotificacion.FALLIDO,
            )
            .order_by(Notificacion.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def resultado_por_asignacion(
        self, asignacion_ids: list[int], empresa_id: int
    ) -> dict[int, tuple[bool, CanalNotificacion | None]]:
        """El último intento de varias asignaciones en UNA sola consulta.
        Sin esto, un listado de 50 filas dispara 50 consultas extra.

        Se resuelve tomando el id más alto por asignación (los ids son
        crecientes, así que el mayor es el intento más reciente) y luego
        trayendo esas filas."""
        if not asignacion_ids:
            return {}

        ultimos = (
            select(func.max(Notificacion.id))
            .where(
                Notificacion.asignacion_id.in_(asignacion_ids),
                Notificacion.empresa_id == empresa_id,
            )
            .group_by(Notificacion.asignacion_id)
        )
        stmt = select(Notificacion).where(Notificacion.id.in_(ultimos))
        return {
            n.asignacion_id: (n.estado == EstadoNotificacion.ENVIADO, n.canal)
            for n in self.db.execute(stmt).scalars().all()
        }

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
