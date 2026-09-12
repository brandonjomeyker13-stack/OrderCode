# app/models/asignacion_taller.py
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base 
from app.db.mixins import TimestampMixin
from app.models.enums import EstadoAsignacion


class AsignacionTaller(Base, TimestampMixin):
    """Una fila por cada porción de un lote asignada a un taller externo."""
    __tablename__ = "asignaciones_taller"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lote_id: Mapped[int] = mapped_column(
        ForeignKey("lotes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    taller_id: Mapped[int] = mapped_column(
        ForeignKey("talleres.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Evento de asignación
    cantidad_asignada: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_asignacion: Mapped[date] = mapped_column(Date, nullable=False)

    # Acumulado de lo devuelto y fecha de la ÚLTIMA entrega. Se conservan
    # denormalizados porque son el camino rápido para saber el saldo sin sumar
    # eventos; el detalle de cada entrega vive en `devoluciones`.
    cantidad_devuelta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_devolucion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    estado: Mapped[EstadoAsignacion] = mapped_column(
        Enum(
            EstadoAsignacion,
            name="estado_asignacion_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=EstadoAsignacion.ASIGNADO,
        index=True,
    )
    lote: Mapped["Lote"] = relationship(back_populates="asignaciones")
    taller: Mapped["Taller"] = relationship()
    incidencias: Mapped[list["Incidencia"]] = relationship(
        back_populates="asignacion", cascade="all, delete-orphan"
    )
    devoluciones: Mapped[list["Devolucion"]] = relationship(
        back_populates="asignacion",
        cascade="all, delete-orphan",
        order_by="Devolucion.fecha",
    )
    conteos_recepcion: Mapped[list["ConteoRecepcion"]] = relationship(
        back_populates="asignacion",
        cascade="all, delete-orphan",
        order_by="ConteoRecepcion.fecha",
    )