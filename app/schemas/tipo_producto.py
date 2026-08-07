# app/schemas/tipo_producto.py
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampSchema
from app.schemas.qr_code import QRCodeOut

# Lo que se le paga al taller por unidad. Opcional: hay empresas que usan la
# app solo para controlar producción y no cargan precios.
_PRECIO = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class TipoProductoCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    referencia: str = Field(min_length=1, max_length=50)
    precio_unitario: Decimal | None = _PRECIO


class TipoProductoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    referencia: str | None = Field(default=None, min_length=1, max_length=50)
    # Cambiarlo afecta solo a las asignaciones futuras: las ya creadas se
    # llevaron su copia del precio (ver AsignacionTaller.precio_unitario).
    precio_unitario: Decimal | None = _PRECIO


class TipoProductoOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    referencia: str
    # Viaja como texto en el JSON ("1500.00"), no como número: es lo que hace
    # Pydantic con Decimal, y es lo correcto para plata -- los números de
    # JavaScript no representan decimales de forma exacta.
    precio_unitario: Decimal | None
    qr_code: QRCodeOut
