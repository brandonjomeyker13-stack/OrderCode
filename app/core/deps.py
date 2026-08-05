# app/core/deps.py
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario

# auto_error=False: si no hay token, dejamos que sea get_current_usuario
# quien lance el error de negocio (UnauthorizedError), no FastAPI directo,
# así el formato de error es consistente en toda la API.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


def get_current_usuario(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if token is None:
        raise UnauthorizedError("No autenticado")

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise UnauthorizedError("Token inválido o expirado")

    usuario_id = payload.get("sub")
    if usuario_id is None:
        raise UnauthorizedError("Token inválido")

    usuario = db.get(Usuario, int(usuario_id))
    if usuario is None or not usuario.activo:
        raise UnauthorizedError("Usuario no válido")

    # Se revisa en cada request (no solo al iniciar sesión) para que pausar
    # una empresa por falta de pago tenga efecto de inmediato, incluso para
    # quien ya tenía una sesión abierta -- no hay que esperar a que expire
    # su access token (hasta 30 min) para que deje de poder usar la API.
    if not usuario.empresa.activo:
        raise ForbiddenError("El acceso de tu empresa está pausado. Contacta al administrador de tu cuenta.")

    return usuario


def require_admin(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
    if usuario.rol != RolUsuario.ADMIN:
        raise ForbiddenError("Esta acción requiere rol de administrador")
    return usuario