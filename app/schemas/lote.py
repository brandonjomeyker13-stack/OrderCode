# app/schemas/lote.py
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EstadoLote
from app.schemas.common import TimestampSchema
from app.schemas.tipo_producto import TipoProductoOut


class LoteCreate(BaseModel):
    tipo_producto_id: int
    cantidad_total: int = Field(gt=0)
    fecha_registro: date


class LoteUpdate(BaseModel):
    fecha_entrega_cliente: date | None = None
    estado: EstadoLote | None = None


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