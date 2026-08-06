# tests/test_sesiones.py
"""
Ciclo de vida de la sesión: rotación del refresh token, tolerancia a
llamadas simultáneas, detección de cookie robada, logout y bloqueo por
intentos fallidos.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import RateLimitedError, UnauthorizedError
from app.core.security import hash_token
from app.models.refresh_token import RefreshToken
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService
from tests.conftest import PASSWORD_DE_PRUEBA


def _simular_paso_del_tiempo(db: Session, raw_token: str, segundos: int) -> None:
    """Envejece la rotación de un token para no tener que esperar de verdad."""
    token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
    ).scalar_one()
    db.execute(
        RefreshToken.__table__.update()
        .where(RefreshToken.id == token.id)
        .values(rotated_at=datetime.now(timezone.utc) - timedelta(seconds=segundos))
    )
    db.commit()


def test_el_token_rota_en_cada_uso(db: Session, admin: Usuario):
    auth = AuthService(db)
    _, token_inicial = auth.emitir_tokens(admin, ip=None, user_agent=None)

    _, _, token_nuevo = auth.refrescar_access_token(token_inicial)

    assert token_nuevo is not None
    assert token_nuevo != token_inicial


def test_uso_diario_prolongado_no_desloguea(db: Session, admin: Usuario):
    """Con la huella, la persona entra a diario sin volver a escribir la
    contraseña: encadenar rotaciones tiene que seguir funcionando."""
    auth = AuthService(db)
    _, token = auth.emitir_tokens(admin, ip=None, user_agent=None)

    for _ in range(10):
        _, _, token = auth.refrescar_access_token(token)
        assert token is not None


def test_dos_pestanas_a_la_vez_no_desloguean(db: Session, admin: Usuario):
    """Dentro de la ventana de gracia, reusar el token anterior es una
    carrera normal entre pestañas, no un robo."""
    auth = AuthService(db)
    _, token_inicial = auth.emitir_tokens(admin, ip=None, user_agent=None)

    auth.refrescar_access_token(token_inicial)  # pestaña A rota
    access_token, _, token_devuelto = auth.refrescar_access_token(token_inicial)  # pestaña B

    assert access_token is not None, "la segunda pestaña quedó deslogueada"
    assert token_devuelto is None, "no debe pisar la cookie que ya rotó la otra pestaña"


def test_token_robado_cierra_todas_las_sesiones(db: Session, admin: Usuario):
    """Reusar un token ya canjeado mucho después solo se explica porque
    alguien copió la cookie: ahí no se puede distinguir al dueño real del
    atacante, así que se cierra todo y ambos deben volver a entrar."""
    auth = AuthService(db)
    _, token_viejo = auth.emitir_tokens(admin, ip=None, user_agent=None)
    _, _, token_legitimo = auth.refrescar_access_token(token_viejo)

    _simular_paso_del_tiempo(db, token_viejo, settings.REFRESH_TOKEN_GRACIA_SEGUNDOS + 60)

    with pytest.raises(UnauthorizedError):
        auth.refrescar_access_token(token_viejo)

    with pytest.raises(UnauthorizedError):
        auth.refrescar_access_token(token_legitimo)


def test_logout_invalida_la_sesion(db: Session, admin: Usuario):
    auth = AuthService(db)
    _, token = auth.emitir_tokens(admin, ip=None, user_agent=None)

    auth.cerrar_sesion(token)

    with pytest.raises(UnauthorizedError):
        auth.refrescar_access_token(token)


def test_token_vencido_no_sirve(db: Session, admin: Usuario):
    auth = AuthService(db)
    _, token = auth.emitir_tokens(admin, ip=None, user_agent=None)

    fila = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
    ).scalar_one()
    fila.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    with pytest.raises(UnauthorizedError):
        auth.refrescar_access_token(token)


def test_bloqueo_tras_varios_intentos_fallidos(db: Session, admin: Usuario):
    """Fuerza bruta: al llegar al tope se responde 429 (no 401) y con
    Retry-After, para que el cliente sepa cuándo reintentar."""
    auth = AuthService(db)
    credenciales_malas = LoginRequest(email=admin.email, password="contrasena-incorrecta")

    for _ in range(settings.LOGIN_MAX_INTENTOS):
        with pytest.raises(UnauthorizedError):
            auth.autenticar(credenciales_malas)

    with pytest.raises(RateLimitedError) as error:
        auth.autenticar(LoginRequest(email=admin.email, password=PASSWORD_DE_PRUEBA))
    assert error.value.retry_after_seconds > 0


def test_login_correcto_limpia_los_intentos(db: Session, admin: Usuario):
    auth = AuthService(db)
    with pytest.raises(UnauthorizedError):
        auth.autenticar(LoginRequest(email=admin.email, password="mala"))

    auth.autenticar(LoginRequest(email=admin.email, password=PASSWORD_DE_PRUEBA))

    db.refresh(admin)
    assert admin.intentos_fallidos == 0
    assert admin.bloqueado_hasta is None
