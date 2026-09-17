# app/models/lote.py
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer, String
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
    #: Color escrito a mano en el tendido. Convive con `color_id` porque los
    #: cortes viejos siguen apuntando al catálogo; los nuevos no lo usan.
    color_nombre: Mapped[str | None] = mapped_column(String(60), nullable=True)
    color_nombre_normalizado: Mapped[str | None] = mapped_column(String(60), nullable=True)
    #: Capas de ESTE color en el tendido. Si está puesto, la cantidad de la
    #: línea es capas_color × proporciones, y al taller solo se mandan
    #: proporciones enteras.
    capas_color: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Cuántas veces aparece la prenda en el molde. En los cortes nuevos SÍ
    #: multiplica: unidades = capas_color × proporciones.
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

    @property
    def nombre_color(self) -> str | None:
        """Como se lee el color: el texto del tendido, o el del catálogo."""
        if self.color_nombre:
            return self.color_nombre
        if self.color is not None:
            return self.color.nombre
        return None

    @property
    def clave_color(self) -> str | None:
        """Para agrupar 'Negro' y 'negro' en la misma fila de inventario."""
        if self.color_nombre_normalizado:
            return self.color_nombre_normalizado
        if self.color is not None:
            return self.color.nombre_normalizado
        return None

    @property
    def es_por_proporciones(self) -> bool:
        return self.capas_color is not None