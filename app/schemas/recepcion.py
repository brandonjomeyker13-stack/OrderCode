# app/schemas/recepcion.py
"""
Las dos formas de la recepción, una por puesto.

Aquí es donde el conteo a ciegas deja de ser una promesa. No hay un schema con
campos opcionales que se rellenan o no según quién pregunte: hay DOS schemas,
y el de bodega no declara ningún campo de cantidad enviada. No se puede
olvidar ocultar un campo que no existe.

Lo que bodega manda tampoco se valida contra lo que se envió, y eso es a
propósito: el sistema entero existe para el caso en que las dos cifras no
coincidan. Rechazar el conteo que no cuadra obligaría a bodega a adivinar el
número correcto -- y el mensaje de rechazo se lo diría.
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EstadoConteo
from app.schemas.common import MAX_UNIDADES, TimestampSchema
from app.schemas.taller import TallerOut


class ConteoCreate(BaseModel):
    """Lo que bodega anota cuando llega un bulto.

    `cantidad_buena` y `cantidad_danada` se piden por separado porque al
    confirmarse siguen caminos distintos: una descuenta saldo del taller y la
    otra se convierte en merma. Pedirlo después sería pedirle a bodega que
    recuerde algo que ya tenía delante.
    """

    asignacion_id: int
    cantidad_buena: int = Field(ge=0, le=MAX_UNIDADES)
    cantidad_danada: int = Field(default=0, ge=0, le=MAX_UNIDADES)
    fecha: date
    nota: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _algo_tiene_que_haber_llegado(self) -> "ConteoCreate":
        # Único límite del reporte, y no es una comparación contra lo enviado:
        # un conteo de cero y cero no es un conteo, es un formulario vacío.
        if self.cantidad_buena + self.cantidad_danada == 0:
            raise ValueError(
                "Anota al menos una unidad. Si el taller no trajo nada, no registres nada."
            )
        return self


class ConteoUpdate(BaseModel):
    """Corrección del propio reporte, mientras corte todavía no lo confirma.

    Es la salida cuando la cifra no cuadra: hablan, bodega vuelve a contar y
    corrige. Por eso no hace falta un estado de "rechazado".
    """

    cantidad_buena: int | None = Field(default=None, ge=0, le=MAX_UNIDADES)
    cantidad_danada: int | None = Field(default=None, ge=0, le=MAX_UNIDADES)
    fecha: date | None = None
    nota: str | None = Field(default=None, max_length=1000)


class PendienteDeRecibirOut(BaseModel):
    """Un bulto que todavía está en el taller, visto por bodega.

    Lleva de qué producto y de qué taller es -- que es lo que bodega necesita
    para saber qué tiene delante -- y ni una sola cantidad. La lista dice QUÉ
    puede llegar, nunca CUÁNTO.
    """

    model_config = ConfigDict(from_attributes=True)

    asignacion_id: int
    lote_id: int
    taller: TallerOut
    producto: str
    referencia: str
    #: Sin esto, dos bultos del mismo producto en colores distintos salen como
    #: dos filas idénticas y bodega no sabe cuál tiene delante. No es una
    #: cantidad: se puede mostrar sin romper el conteo a ciegas.
    color: str | None
    #: "Corte 07 · 12 sep". La identidad que se dice en voz alta, mejor que un
    #: id interno para buscar el bulto entre varios.
    corte: str | None
    fecha_asignacion: date
    #: Cuántos conteos ya anotó bodega para este bulto, para que sepa si es la
    #: primera tanda o ya lleva varias. Es un conteo de eventos, no de piezas.
    conteos_registrados: int


class ConteoBodegaOut(TimestampSchema):
    """El reporte, devuelto a quien lo escribió.

    Lo único que le repite a bodega es lo que ella misma tecleó. Ningún campo
    de aquí sale de `AsignacionTaller.cantidad_asignada` ni se deriva de él.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    asignacion_id: int
    lote_id: int
    taller: TallerOut
    producto: str
    color: str | None
    corte: str | None
    cantidad_buena: int
    cantidad_danada: int
    fecha: date
    nota: str | None
    estado: EstadoConteo
    #: Para que bodega sepa si corte ya lo miró, sin tener que preguntarlo.
    confirmado_at: datetime | None


class ConteoPorConfirmarOut(TimestampSchema):
    """El mismo reporte, visto por corte. Esta sí lleva las dos cifras.

    Es el momento del producto: aquí se ve, una al lado de la otra, la
    cantidad que salió y la que volvió. `diferencia` se calcula en el servidor
    y no en el front, para que la cifra que se discute sea una sola.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    asignacion_id: int
    lote_id: int
    taller: TallerOut
    producto: str
    referencia: str
    color: str | None
    corte: str | None

    cantidad_buena: int
    cantidad_danada: int
    fecha: date
    nota: str | None
    estado: EstadoConteo

    #: Lo que corte mandó al taller y lo que todavía no ha vuelto.
    cantidad_asignada: int
    cantidad_pendiente: int
    #: contado - pendiente. Negativo = faltó, positivo = llegó de más, cero =
    #: cuadra. Se manda con signo porque "faltan 3" y "sobran 3" son dos
    #: conversaciones distintas con el taller.
    diferencia: int

    #: Quién contó. Con una sola cuenta por puesto hoy es siempre la misma
    #: persona, pero la pregunta "¿quién anotó esto?" se hace igual, y sin la
    #: columna no tiene respuesta.
    contado_por: str | None
    confirmado_por: str | None
    confirmado_at: datetime | None
