# app/schemas/usuario.py
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import RolUsuario
from app.schemas.common import TimestampSchema


class UsuarioCreate(BaseModel):
    """Entrada al crear un usuario. `password` en texto plano solo vive aquí,
    de memoria, el tiempo que tarda en pasar por security.hash_password()."""
    nombre: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # Sin valor por defecto a propósito. Con dos roles, equivocarse costaba
    # poco; con cuatro, uno de ellos (CORTE) ve todo lo que el conteo a ciegas
    # le oculta a BODEGA. Que el admin elija explícitamente es más seguro que
    # que el sistema adivine, y el error se ve como un 422 claro y no como un
    # usuario creado con el rol que no era.
    rol: RolUsuario


class UsuarioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=150)
    rol: RolUsuario | None = None
    activo: bool | None = None


class CambioPassword(BaseModel):
    password_actual: str
    password_nueva: str = Field(min_length=8, max_length=128)


class ConfigurarPasswordInicial(BaseModel):
    """Para cuentas creadas por Google Sign-In (ver password_configurada en
    UsuarioOut) -- a diferencia de CambioPassword, no pide la contraseña
    actual porque no existe una real que el usuario conozca."""
    password_nueva: str = Field(min_length=8, max_length=128)


class UsuarioOut(TimestampSchema):
    """Nunca incluye password_hash. Esto es intencional: si algún día alguien
    agrega ese campo aquí por error, es una fuga de datos sensibles."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nombre: str
    email: EmailStr
    rol: RolUsuario
    activo: bool
    email_verificado: bool
    # False -> el front debe mandar a esta cuenta a "configura tu cuenta"
    # (viene de Google Sign-In y todavía no tiene contraseña real).
    password_configurada: bool