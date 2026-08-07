# app/models/notificacion_leida.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class NotificacionLeida(Base, TimestampMixin):
    """
    Marca de que un usuario ya vio un aviso del centro de notificaciones.

    Solo se guarda la MARCA, no el aviso. Los avisos se calculan al momento a
    partir del estado real (lotes atrasados, envíos fallidos, incidencias
    recientes), así que nunca quedan desactualizados: si un lote atrasado se
    entrega, su aviso simplemente deja de aparecer.

    Guardar el aviso como fila traería el problema contrario -- una fila
    diciendo "lote 42 atrasado" seguiría ahí después de que el taller lo
    entregue, y habría que salir a limpiarla cada vez que cambia algo.

    La marca es POR USUARIO: que el dueño lea un aviso no debería marcarlo
    como visto para el resto del equipo.
    """
    __tablename__ = "notificaciones_leidas"
    __table_args__ = (
        UniqueConstraint("usuario_id", "clave", name="uq_notificacion_leida_usuario_clave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Identidad estable del aviso, ej. "lote_atrasado:asignacion:42". Tiene que
    # ser reproducible: es lo que permite reconocer el mismo aviso entre una
    # recarga y otra sin haberlo guardado.
    clave: Mapped[str] = mapped_column(String(150), nullable=False)
    leida_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
