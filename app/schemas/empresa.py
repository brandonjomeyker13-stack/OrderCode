# app/schemas/empresa.py
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampSchema


class EmpresaCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)


class EmpresaUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    activo: bool | None = None


class EmpresaOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool
    usuario_propietario_id: int | None = None


class EmpresaConEstadisticas(EmpresaOut):
    """Extiende EmpresaOut con datos calculados (no columnas reales de la tabla)."""
    total_talleres: int
    total_usuarios: int