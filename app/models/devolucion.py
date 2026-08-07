# app/models/devolucion.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Devolucion(Base, TimestampMixin):
    """
    Una entrega concreta del taller: cuánto trajo y cuándo.

    Existe porque `AsignacionTaller.cantidad_devuelta` es un ACUMULADO y
    `fecha_devolucion` guarda solo la última fecha. Con eso solo, si un taller
    entrega en tres tandas se pierde el detalle de cada una: no se puede saber
    cuánto entregó un día concreto ni cuánto tardó realmente.

    Los campos de la asignación se conservan (los usa medio sistema y son el
    camino rápido para saber el saldo); esta tabla es la fuente de verdad del
    historial.
    """
    __tablename__ = "devoluciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asignacion_id: Mapped[int] = mapped_column(
        ForeignKey("asignaciones_taller.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    asignacion: Mapped["AsignacionTaller"] = relationship(back_populates="devoluciones")
