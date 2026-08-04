# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field

from app.schemas.usuario import UsuarioOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegistroRequest(BaseModel):
    """Body plano para el formulario de registro: una empresa nueva y su
    primer usuario (admin) en una sola petición."""
    nombre_empresa: str = Field(min_length=2, max_length=150)
    nombre: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


class RefreshRequest(BaseModel):
    refresh_token: str