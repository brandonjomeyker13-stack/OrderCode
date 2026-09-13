# app/models/lote.py
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.models.enums import EstadoLote


class Lote(Base, TimestampMixin):
    __tablename__ = "lotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo_producto_id: Mapped[int] = mapped_column(
        ForeignKey("tipos_producto.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # --- La línea del corte: corte + tipo + color ---
    #
    # `lotes` dejó de ser "un lote suelto" y pasó a ser una LÍNEA de un corte.
    # No se renombró la tabla a propósito: de su id cuelgan asignaciones,
    # devoluciones, incidencias y conteos, y moverlo no compra nada que el
    # nombre no compre solo.
    corte_id: Mapped[int | None] = mapped_column(
        ForeignKey("cortes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    #: NULL en las líneas heredadas: el color de lo que se cortó antes de que
    #: existiera el catálogo no está guardado en ninguna parte y no se puede
    #: inventar.
    color_id: Mapped[int | None] = mapped_column(
        ForeignKey("colores.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    #: Cuántas veces aparece la prenda en el molde. Es INFORMATIVO: la
    #: aplicación no multiplica nada con esto, solo lo guarda y lo muestra.
    #: Si algún día se usa para calcular, que sea una decisión escrita, no un
    #: descuido.
    proporciones: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cantidad_total: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_registro: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_entrega_cliente: Mapped[date | None] = mapped_column(Date, nullable=True)

    estado: Mapped[EstadoLote] = mapped_column(
        Enum(
            EstadoLote,
            name="estado_lote_enum",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=EstadoLote.PENDIENTE_ASIGNACION,
        index=True,
    )

    tipo_producto: Mapped["TipoProducto"] = relationship()
    corte: Mapped["Corte | None"] = relationship(back_populates="lineas")
    color: Mapped["Color | None"] = relationship()
    asignaciones: Mapped[list["AsignacionTaller"]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )
    ventas: Mapped[list["Venta"]] = relationship(
        back_populates="lote", cascade="all, delete-orphan"
    )