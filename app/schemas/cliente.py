# app/schemas/cliente.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.common import TimestampSchema


class ClienteCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    telefono: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None


class ClienteUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    telefono: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    activo: bool | None = None


class ClienteOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    telefono: str | None
    email: str | None
    activo: bool