# app/schemas/empresa.py
from datetime import datetime

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


class SolicitarEliminacionCuenta(BaseModel):
    """Pide la contraseña otra vez: es la acción más destructiva del sistema
    y no debe dispararse solo por tener la sesión abierta."""
    password: str


class EmpresaOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool
    usuario_propietario_id: int | None = None
    # Si no es null, la cuenta está programada para borrarse y el front debe
    # avisarlo de forma visible, junto con la opción de cancelar.
    eliminacion_solicitada_at: datetime | None = None


class EmpresaConEstadisticas(EmpresaOut):
    """Extiende EmpresaOut con datos calculados (no columnas reales de la tabla)."""
    total_talleres: int
    total_usuarios: int