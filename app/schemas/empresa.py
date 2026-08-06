# app/schemas/empresa.py
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TimestampSchema


class EmpresaCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)


class EmpresaUpdate(BaseModel):
    """`activo` NO va aquí a propósito: es el interruptor de pago y solo se
    cambia a mano desde la base de datos. Si se expusiera, el admin de una
    empresa pausada por falta de pago podría reactivarse solo con un PATCH
    a /empresas/actual (ese endpoint pide rol admin, y todo cliente es
    admin de su propia empresa)."""
    nombre: str | None = Field(default=None, min_length=2, max_length=150)


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