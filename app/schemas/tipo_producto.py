# app/schemas/tipo_producto.py
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampSchema
from app.schemas.qr_code import QRCodeOut


class TipoProductoCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    referencia: str = Field(min_length=1, max_length=50)


class TipoProductoUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    referencia: str | None = Field(default=None, min_length=1, max_length=50)


class TipoProductoOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    referencia: str
    qr_code: QRCodeOut
