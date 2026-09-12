# app/models/venta.py
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Venta(Base, TimestampMixin):
    """
    Una salida de inventario: prendas que ya no están en la bodega.

    Es lo último del recorrido. Corte manda al taller, bodega cuenta lo que
    vuelve, corte confirma, y en ese momento las unidades quedan LISTAS. Esta
    tabla las saca.

    Guarda la cantidad y nada más de plata: la aplicación dejó de manejar
    dinero (migración c4a83f1e6db0) y el precio lo organizan por fuera. Aquí
    solo importa que la prenda salió, para que el inventario no siga diciendo
    que está.

    Se cuelga del lote y no del tipo de producto a propósito: dos lotes del
    mismo producto son dos tandas distintas, y cuando el lote se convierta en
    una línea de corte (corte + tipo + color), esta referencia sigue apuntando
    a lo correcto sin migrar nada.
    """

    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lote_id: Mapped[int] = mapped_column(
        ForeignKey("lotes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: A quién se le mandó, o cualquier referencia que le sirva a la empresa
    #: para reconocer la salida. Texto libre: no hay módulo de clientes y no
    #: va a haberlo (se eliminó en b7d1e9c40a12 porque nadie lo usaba).
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Quién la registró. SET NULL: borrar a una persona no borra el
    #: historial de salidas de la empresa.
    registrada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    lote: Mapped["Lote"] = relationship(back_populates="ventas")
