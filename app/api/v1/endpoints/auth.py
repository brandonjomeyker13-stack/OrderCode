# app/api/v1/endpoints/auth.py
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_usuario
from app.core.rate_limit import obtener_ip, verificar_limite_ip
from app.core.exceptions import UnauthorizedError
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.auth import (
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegistroRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.usuario import UsuarioOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )


@router.post("/registro", response_model=TokenResponse, status_code=201)
def registrar(
    data: RegistroRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Alta de un nuevo tenant: crea la empresa y su usuario admin."""
    verificar_limite_ip(db, obtener_ip(request), "POST /auth/registro")
    service = AuthService(db)
    usuario = service.registrar_empresa_y_admin(data)
    access_token, raw_refresh = service.emitir_tokens(
        usuario, ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token, usuario=UsuarioOut.model_validate(usuario))


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"description": "Credenciales inválidas"},
        429: {"description": "Cuenta bloqueada temporalmente por intentos fallidos"},
    },
)
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


@router.post(
    "/google",
    response_model=TokenResponse,
    responses={401: {"description": "Token de Google inválido o correo no verificado"}},
)
def login_con_google(
    data: GoogleAuthRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Recibe el `id_token` (credential) que entrega Google Identity Services
    en el front -- no un authorization code de OAuth clásico."""
    verificar_limite_ip(db, obtener_ip(request), "POST /auth/google")
    service = AuthService(db)
    usuario = service.autenticar_con_google(data.id_token, data.nombre_empresa)
    access_token, raw_refresh = service.emitir_tokens(
        usuario, ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token, usuario=UsuarioOut.model_validate(usuario))


@router.post("/forgot-password", status_code=204)
def olvide_password(
    data: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
):
    """Siempre responde 204 exista o no el correo -- evita enumeración de
    cuentas. Si existe, se manda el enlace por correo (ver AuthService)."""
    verificar_limite_ip(db, obtener_ip(request), "POST /auth/forgot-password")
    AuthService(db).iniciar_recuperacion_password(data.email)


@router.post(
    "/reset-password",
    status_code=204,
    responses={401: {"description": "Enlace inválido o expirado"}},
)
def restablecer_password(
    data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)
):
    verificar_limite_ip(db, obtener_ip(request), "POST /auth/reset-password")
    AuthService(db).restablecer_password(data.token, data.password_nueva)


@router.post("/refresh", response_model=TokenResponse)
def refrescar(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_refresh = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh is None:
        raise UnauthorizedError("No hay sesión activa")

    service = AuthService(db)
    access_token, usuario, nuevo_refresh = service.refrescar_access_token(raw_refresh)
    # None = esta llamada cayó en la ventana de gracia (otra pestaña ya rotó);
    # ahí no se toca la cookie para no pisar la que acaba de quedar buena.
    if nuevo_refresh is not None:
        _set_refresh_cookie(response, nuevo_refresh)
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