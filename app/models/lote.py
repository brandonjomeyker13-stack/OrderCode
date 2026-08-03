# app/models/lote.py
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base 
from app.db.mixins import TimestampMixin
from app.models.enums import EstadoLote


class Lote(Base, TimestampMixin):
    """
    La 'masa general' generada en el paso de entrada/producción interna,
    antes de repartirse entre talleres externos. Genérico: puede ser un
    corte de tela, un lote de piezas de cuero cortadas, etc.
    """
    __tablename__ = "lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_producto_id: Mapped[int] = mapped_column(
        ForeignKey("tipos_producto.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    cantidad_total: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_registro: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_entrega_cliente: Mapped[date | None] = mapped_column(Date, nullable=True)

    estado: Mapped[EstadoLote] = mapped_column(
        Enum(EstadoLote, name="estado_lote_enum"),
        nullable=False,
        default=EstadoLote.PENDIENTE_ASIGNACION,
        index=True,
    )

    tipo_producto: Mapped["TipoProducto"] = relationship()
    asignaciones: Mapped[list["AsignacionTaller"]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )