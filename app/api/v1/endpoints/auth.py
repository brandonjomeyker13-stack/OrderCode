# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_usuario
from app.core.exceptions import UnauthorizedError
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.empresa import EmpresaCreate
from app.schemas.usuario import UsuarioCreate, UsuarioOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.is_production,  # False en local para poder probar sin HTTPS
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",  # la cookie no viaja a ninguna otra ruta de la API
    )


class RegistroRequest(EmpresaCreate):
    pass


@router.post("/register", response_model=TokenResponse, status_code=201)
def registrar(
    empresa_in: EmpresaCreate,
    admin_in: UsuarioCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Alta de un nuevo tenant: crea la empresa y su usuario admin."""
    service = AuthService(db)
    usuario = service.registrar_empresa_y_admin(empresa_in, admin_in)
    access_token, raw_refresh = service.emitir_tokens(
        usuario, ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token, usuario=UsuarioOut.model_validate(usuario))


@router.post("/login", response_model=TokenResponse)
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    usuario = service.autenticar(credentials)
    access_token, raw_refresh = service.emitir_tokens(
        usuario, ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token, usuario=UsuarioOut.model_validate(usuario))


@router.post("/refresh", response_model=TokenResponse)
def refrescar(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh is None:
        raise UnauthorizedError("No hay sesión activa")

    service = AuthService(db)
    access_token, usuario = service.refrescar_access_token(raw_refresh)
    return TokenResponse(access_token=access_token, usuario=UsuarioOut.model_validate(usuario))


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh:
        AuthService(db).cerrar_sesion(raw_refresh)
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE_NAME, path="/api/v1/auth")


@router.get("/me", response_model=UsuarioOut)
def obtener_perfil(usuario: Usuario = Depends(get_current_usuario)):
    return usuario