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


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password_nueva: str = Field(min_length=8, max_length=128)


class GoogleAuthRequest(BaseModel):
    """`id_token` es el credential que devuelve Google Identity Services en
    el front (no un access_token de OAuth clásico)."""
    id_token: str
    nombre_empresa: str | None = Field(default=None, min_length=2, max_length=150)