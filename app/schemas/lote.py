# app/schemas/lote.py
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EstadoLote
from app.schemas.common import MAX_UNIDADES, TimestampSchema
from app.schemas.tipo_producto import TipoProductoOut


class LoteCreate(BaseModel):
    tipo_producto_id: int
    cantidad_total: int = Field(gt=0, le=MAX_UNIDADES)
    fecha_registro: date


class LoteUpdate(BaseModel):
    """Corrección de un error de captura -- no cambia el estado del lote,
    eso ya tiene sus propios flujos (asignar, devolver, cerrar_hacia_cliente)."""

    cantidad_total: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)
    fecha_registro: date | None = None


class LoteOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    cantidad_total: int
    fecha_registro: date
    fecha_entrega_cliente: date | None
    estado: EstadoLote
    tipo_producto: TipoProductoOut


class LoteConDisponibilidad(LoteOut):
    """Para la vista del QR: cuánto de este lote sigue sin asignar."""
    cantidad_asignada_total: int
    cantidad_disponible: int
    #: Del mismo producto pueden salir varias líneas del mismo corte en
    #: colores distintos. Sin esto, al escanear el QR salen filas idénticas y
    #: no hay forma de saber cuál es cuál.
    color: str | None = None
    corte: str | None = None