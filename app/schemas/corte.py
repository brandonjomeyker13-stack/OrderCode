# app/schemas/corte.py
"""
El corte y sus líneas.

Un corte se registra ENTERO, de una vez: la cabecera y todas sus líneas en la
misma llamada. No hay "crear corte" y luego "agregarle líneas", porque un
tendido sin líneas no es nada y dejarlo a medias es dejar basura en la base
que alguien tiene que limpiar después.
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import MAX_UNIDADES, TimestampSchema

MAX_LINEAS = 50


# --- Colores ---


class ColorCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=60)
    #: El puntito del chip. Opcional: un nombre bien escrito ya sirve.
    hex: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("nombre")
    @classmethod
    def _sin_espacios_de_sobra(cls, v: str) -> str:
        limpio = " ".join(v.split())
        if not limpio:
            raise ValueError("El nombre del color no puede estar vacío")
        return limpio


class ColorUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=60)
    hex: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    activo: bool | None = None


class ColorOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    hex: str | None
    activo: bool


# --- Líneas del corte ---


class LineaCorteCreate(BaseModel):
    """Una combinación tipo + color con su cantidad.

    `color_id` es opcional porque no toda maquila trabaja por color, y
    obligarlo convertiría el catálogo en un trámite antes de poder registrar
    nada. Cuando se manda, tiene que ser un color de la propia empresa.
    """

    tipo_producto_id: int
    color_id: int | None = None
    cantidad: int = Field(gt=0, le=MAX_UNIDADES)
    #: Cuántas veces aparece la prenda en el molde. INFORMATIVO: no multiplica
    #: nada. Si alguna vez se usa para calcular, que sea una decisión escrita.
    proporciones: int | None = Field(default=None, gt=0, le=1000)


class LineaCorteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    #: Es el id de `lotes`. Se llama lote_id porque eso es lo que el resto de
    #: la API lleva llamando así desde siempre, y renombrarlo aquí obligaría a
    #: renombrarlo en las asignaciones, las devoluciones y los conteos.
    lote_id: int
    tipo_producto_id: int
    producto: str
    referencia: str
    color: str | None
    color_hex: str | None
    cantidad: int
    proporciones: int | None
    estado: str


# --- El corte ---


class CorteCreate(BaseModel):
    fecha: date
    #: Lo que la encargada teclea ANTES de desglosar. Se guarda tal cual y
    #: jamás se recalcula: si no cuadra con la suma de las líneas, eso es
    #: exactamente lo que hay que poder ver.
    cantidad_declarada: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)
    lineas: list[LineaCorteCreate] = Field(min_length=1, max_length=MAX_LINEAS)

    @model_validator(mode="after")
    def _sin_lineas_repetidas(self) -> "CorteCreate":
        # Dos líneas del mismo tipo y color son la misma cosa contada dos
        # veces: al asignarlas a talleres nadie sabría cuál es cuál, y el
        # inventario mostraría dos filas idénticas.
        vistas = {(linea.tipo_producto_id, linea.color_id) for linea in self.lineas}
        if len(vistas) != len(self.lineas):
            raise ValueError(
                "Hay dos líneas con el mismo producto y color. Súmalas en una sola."
            )
        return self


class CorteUpdate(BaseModel):
    """Corrección de la cabecera. Las líneas no se tocan por aquí: cada una es
    un lote con su propio historial de asignaciones y devoluciones."""

    fecha: date | None = None
    cantidad_declarada: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)


class CorteOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    #: 1..100 del ciclo. NULL en los cortes históricos, de antes del ciclo.
    numero: int | None
    fecha: date
    #: La identidad que se dice en voz alta: "corte 07 del 12 de septiembre".
    #: Pueden convivir dos corte 07 de meses distintos, por eso lleva fecha.
    etiqueta: str

    cantidad_declarada: int | None
    cantidad_desglosada: int
    #: declarada - desglosada. Cero o None cuando no hay nada que comparar.
    #: La aplicación AVISA, no bloquea: el mismo criterio que en la recepción.
    diferencia: int | None

    cerrado_at: datetime | None
    lineas: list[LineaCorteOut]
