# app/core/security.py
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

_ph = PasswordHasher()


# --- Hasheo de contraseñas (Argon2id) ---

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return _ph.verify(hashed_password, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def needs_rehash(hashed_password: str) -> bool:
    return _ph.check_needs_rehash(hashed_password)


# --- JWT (access token) ---

def create_access_token(subject: str, empresa_id: int, rol: str) -> str:
    """
    `subject` es el usuario_id como string. empresa_id y rol viajan en el
    payload para no tener que consultar la DB en cada request solo para
    saber a qué tenant pertenece el usuario -- igual se revalida contra
    DB en get_current_usuario para detectar usuarios desactivados.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "empresa_id": empresa_id, "rol": rol, "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Lanza jose.JWTError si el token es inválido, está mal firmado o expiró."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# --- Refresh token (opaco, no JWT) ---

def generate_refresh_token() -> str:
    """Token aleatorio de alta entropía, no un JWT -- no necesita ser
    autocontenido, solo un identificador imposible de adivinar."""
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    """SHA-256 es suficiente aquí (no Argon2): el token ya es aleatorio de
    alta entropía, no una contraseña elegida por un humano. Hashearlo solo
    protege contra lectura directa de la tabla refresh_tokens."""
    return hashlib.sha256(raw_token.encode()).hexdigest()