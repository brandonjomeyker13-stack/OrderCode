# app/schemas/taller.py
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampSchema


class TallerCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    numero_taller: str = Field(min_length=1, max_length=30)
    telefono: str = Field(min_length=7, max_length=20)
    direccion: str | None = Field(default=None, max_length=255)


class TallerUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    telefono: str | None = Field(default=None, min_length=7, max_length=20)
    direccion: str | None = Field(default=None, max_length=255)
    activo: bool | None = None


class TallerOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    numero_taller: str
    telefono: str
    direccion: str | None
    activo: bool