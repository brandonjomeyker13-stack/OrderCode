# app/models/asignacion_taller.py
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric
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

    # COPIA del precio que tenía el tipo de producto al crear la asignación.
    # Está duplicado a propósito: si el monto a pagar se calculara leyendo el
    # precio actual del producto, subir la tarifa en marzo reescribiría lo que
    # dicen los cortes de enero y febrero -- cortes que ya se pagaron. Acá
    # queda congelado el precio que se pactó cuando salió el trabajo.
    #
    # Nulo en las asignaciones anteriores a que existieran las tarifas, y en
    # empresas que no cargan precios. El ranking reporta aparte cuántas
    # unidades quedaron sin tarifa, para que un total bajo no pase por bueno.
    precio_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

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