# app/models/conteo_recepcion.py
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import EstadoConteo


class ConteoRecepcion(Base, TimestampMixin):
    """
    Lo que bodega contó cuando llegó el bulto, ANTES de que nadie lo dé por
    bueno.

    Es una tabla aparte de `devoluciones` y esa es toda la idea. Una fila de
    `devoluciones` es un hecho firme: descuenta el saldo del taller y mueve el
    estado del lote. Una fila de aquí es el reporte de una persona, y puede
    no cuadrar -- de hecho el sistema existe para el caso en que no cuadre.

    Así funciona la planta: la muchacha de bodega cuenta sin saber cuánto se
    envió (ese es el control, no un detalle de permisos), anota lo que le dio
    y eso queda REPORTADO. Corte ve que hay algo por confirmar, compara contra
    lo que mandó, hablan si la cifra no coincide, y solo entonces confirma.
    Al confirmar nace la `Devolucion` de verdad.

    Por qué no un estado dentro de `devoluciones`: media docena de consultas
    ya suman esa tabla para saber el saldo de un taller. Si un reporte sin
    confirmar viviera ahí, cada una de esas consultas tendría que acordarse de
    filtrar, y la que se olvide daría por entregado algo que nadie revisó.
    Separar las tablas hace que olvidarse sea imposible.
    """

    __tablename__ = "conteos_recepcion"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asignacion_id: Mapped[int] = mapped_column(
        ForeignKey("asignaciones_taller.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Unidades que llegaron en buen estado, tal como las contó bodega.
    cantidad_buena: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Unidades que llegaron dañadas. Se piden por separado porque al
    #: confirmar siguen caminos distintos: unas descuentan saldo y las otras
    #: se convierten en merma.
    cantidad_danada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: El día en que llegó el bulto, que no siempre es el día en que se anota.
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: Lo que bodega quiera dejarle dicho a corte ("el taller dice que faltan
    #: 3", "vino sin la bolsa"). Es el canal que hoy es una llamada.
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)

    estado: Mapped[EstadoConteo] = mapped_column(
        Enum(
            EstadoConteo,
            name="estado_conteo_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    # --- Quién hizo qué ---
    #
    # Estas dos columnas son el control de cuatro ojos escrito en la base. Si
    # no se sabe quién contó y quién confirmó, "lo revisaron dos personas" es
    # una costumbre y no un hecho comprobable. SET NULL y no CASCADE: borrar a
    # una persona no puede borrar el historial de la empresa.
    contado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    confirmado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    confirmado_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: La devolución que nació al confirmar. Es el puente entre el reporte y
    #: el hecho firme: sin él no habría forma de saber qué conteo produjo qué
    #: descuento cuando alguien pregunte dentro de seis meses.
    devolucion_id: Mapped[int | None] = mapped_column(
        ForeignKey("devoluciones.id", ondelete="SET NULL"), nullable=True
    )

    asignacion: Mapped["AsignacionTaller"] = relationship(back_populates="conteos_recepcion")

    @property
    def cantidad_total(self) -> int:
        """Todo lo que bodega dice que llegó, bueno y dañado."""
        return self.cantidad_buena + self.cantidad_danada
