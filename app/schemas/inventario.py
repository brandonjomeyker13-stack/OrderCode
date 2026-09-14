# app/schemas/inventario.py
"""
Lo que ya está listo para salir, y lo que salió.

El disponible NO se guarda en ninguna columna: se calcula como lo devuelto y
confirmado menos lo vendido. Es deliberado. Un saldo guardado se desincroniza
en cuanto alguien corrige una devolución vieja o borra una merma, y este
sistema tiene correcciones por todas partes -- el admin puede editar
asignaciones, mermas y devoluciones. Un número calculado no se puede quedar
viejo.
"""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import MAX_UNIDADES, TimestampSchema


class TandaDisponibleOut(BaseModel):
    """Una tanda con existencias, y cuántas le quedan.

    No es para mostrar: es para que la salida sepa de qué lote descontar. Una
    venta se descuenta de UN lote, pero quien despacha pide "20 negras" sin
    tener por qué saber de qué corte salieron.
    """

    model_config = ConfigDict(from_attributes=True)

    lote_id: int
    fecha_registro: date
    cantidad_disponible: int


class LineaInventarioOut(BaseModel):
    """Una prenda en un color: la unidad con la que se vende.

    No es una tanda. Del mismo legging negro pueden quedar unidades de dos
    cortes distintos, y para vender eso es una sola cosa: "leggings negros,
    quedan 50". Las tandas van dentro, en `tandas`, y vienen completas -- si
    se recortaran, la fila mostraría menos de lo que hay.
    """

    model_config = ConfigDict(from_attributes=True)

    tipo_producto_id: int
    producto: str
    referencia: str
    color: str | None
    #: El puntito del chip, si el catálogo lo tiene.
    color_hex: str | None

    #: Unidades que volvieron BIEN del taller y que corte ya confirmó. Lo
    #: dañado no está aquí: no está listo para vender. Las dos cifras cuentan
    #: solo las tandas que aún tienen existencias, no las agotadas.
    cantidad_lista: int
    cantidad_vendida: int
    cantidad_disponible: int

    #: La más vieja primero, que es de donde conviene sacar.
    tandas: list[TandaDisponibleOut]


class ResumenInventarioOut(BaseModel):
    """El inventario completo, con el total arriba para no sumarlo a mano.

    Los totales son de la EMPRESA, no de la página: `lineas` puede traer 50
    filas y `total_disponible` contar las 300 unidades que hay. `total_lineas`
    dice cuántas combinaciones de prenda y color con existencias hay en total,
    para que el frontend sepa si se está quedando corto.
    """

    total_disponible: int
    total_vendido: int
    total_lineas: int
    lineas: list[LineaInventarioOut]


class VentaCreate(BaseModel):
    lote_id: int
    cantidad: int = Field(gt=0, le=MAX_UNIDADES)
    fecha: date
    #: A quién se le mandó, o lo que le sirva a la empresa para reconocer la
    #: salida. Texto libre: no hay módulo de clientes ni va a haberlo.
    nota: str | None = Field(default=None, max_length=1000)


class VentaUpdate(BaseModel):
    """Corrección de captura. `lote_id` no se puede cambiar: mover una salida
    de un lote a otro no es corregir, es rehacer dos inventarios a la vez."""

    cantidad: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)
    fecha: date | None = None
    nota: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _algo_que_cambiar(self) -> "VentaUpdate":
        if self.model_fields_set == set():
            raise ValueError("No mandaste ningún cambio")
        return self


class VentaOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lote_id: int
    producto: str
    referencia: str
    #: La misma razón que en la línea de inventario: sin color y sin corte, el
    #: historial de salidas no dice de cuál de las tandas salió.
    color: str | None
    corte: str | None
    cantidad: int
    fecha: date
    nota: str | None
    registrada_por: str | None
