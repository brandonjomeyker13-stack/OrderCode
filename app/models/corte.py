# app/models/corte.py
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Corte(Base, TimestampMixin):
    """
    Un tendido de tela: se apilan capas y se corta todo junto.

    De un mismo corte salen VARIOS tipos de producto en VARIOS colores, y esa
    combinación -- corte + tipo + color -- es la unidad de la que se habla en
    planta. Cada una de esas combinaciones es una fila de `lotes`, que desde
    esta migración significa "una línea del corte" y no "un lote suelto".

    NO TIENE COLUMNA DE ESTADO, y es deliberado. El avance del corte ("6
    líneas: 4 cerradas, 2 en taller") se calcula sumando sus líneas cuando
    alguien pregunta. Un estado guardado aquí sería un segundo sitio donde
    vive la misma verdad, y dos sitios se desincronizan: basta con que alguien
    corrija una devolución vieja para que el estado del corte quede mintiendo
    y nadie se entere. Además, sin estado no hay tipo enum nuevo en Postgres,
    que es de lejos lo más caro de migrar en esta base (ver d5f2b8a71c39).

    LA IDENTIDAD ES NÚMERO + FECHA. El número va de 1 a 100 y vuelve a
    empezar, así que pueden convivir dos "corte 07" de meses distintos y hay
    que decir cuál. `numero` es NULL en los cortes que la migración creó para
    los lotes que ya existían: son históricos y nunca estuvieron en el ciclo.
    """

    __tablename__ = "cortes"
    __table_args__ = (
        # En Postgres dos NULL no chocan entre sí, así que los cortes
        # históricos (numero NULL) pueden ser varios en la misma fecha sin
        # pelearse. Los del ciclo sí quedan protegidos.
        UniqueConstraint("empresa_id", "numero", "fecha", name="uq_corte_numero_fecha_empresa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: 1..100 del ciclo. NULL = corte histórico, de antes de que el ciclo
    #: existiera. Lo asigna el sistema, nunca el cliente.
    numero: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    #: El día del TENDIDO, que no siempre es el día en que se captura.
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    #: Capas del tendido. En los cortes nuevos es la cifra que se parte por
    #: color; en los viejos queda NULL.
    capas: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: El total que la encargada teclea ANTES de desglosar. Es un dato de
    #: control y jamás se recalcula: si el desglose no le cuadra, eso es
    #: exactamente lo que hay que poder ver. La aplicación avisa, no bloquea
    #: -- el mismo criterio que en la recepción.
    cantidad_declarada: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Acto explícito de cerrar el corte. Es lo único que libera su número
    #: para que el ciclo pueda volver a usarlo.
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Solo en los cortes que creó la migración, uno por lote existente. Es el
    #: hilo con el "#32" que el cliente ve hoy en pantalla.
    origen_lote_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lineas: Mapped[list["Lote"]] = relationship(
        back_populates="corte",
        # Sin delete-orphan: borrar un corte con líneas que ya salieron a
        # talleres sería borrar producción. Lo impide el service, no la base.
        order_by="Lote.id",
    )
    colores: Mapped[list["CorteColor"]] = relationship(
        back_populates="corte",
        cascade="all, delete-orphan",
        order_by="CorteColor.id",
    )

    @property
    def cantidad_desglosada(self) -> int:
        return sum(linea.cantidad_total for linea in self.lineas)
