# app/schemas/taller.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import TimestampSchema


class TallerCreate(BaseModel):
    """`numero_taller` NO se recibe: lo asigna el servidor como consecutivo
    por empresa (ver TallerService.crear). Desde el cliente es imposible
    garantizar que dos altas simultáneas no elijan el mismo número."""
    nombre: str = Field(min_length=2, max_length=150)
    telefono: str = Field(min_length=7, max_length=20)
    # Respaldo para la ficha técnica si WhatsApp no está disponible.
    email: EmailStr | None = None
    direccion: str | None = Field(default=None, max_length=255)


class TallerUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    telefono: str | None = Field(default=None, min_length=7, max_length=20)
    email: EmailStr | None = None
    direccion: str | None = Field(default=None, max_length=255)
    activo: bool | None = None


class TallerOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    numero_taller: str
    telefono: str
    email: str | None
    direccion: str | None
    activo: bool