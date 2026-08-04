# app/core/google_auth.py
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings
from app.core.exceptions import UnauthorizedError

_request = google_requests.Request()


def verificar_id_token_google(token: str) -> dict:
    """
    Verifica firma, expiración y audience de un ID token emitido por Google
    Identity Services (Sign in with Google del front). Lanza
    UnauthorizedError en vez de dejar pasar la excepción cruda de la
    librería -- los services de negocio no deberían conocer detalles de
    google-auth.

    Devuelve el payload verificado: incluye al menos "email",
    "email_verified", "sub" (id único de la cuenta de Google) y "name".
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise UnauthorizedError("Google Sign-In no está configurado en el servidor")
    try:
        return google_id_token.verify_oauth2_token(token, _request, settings.GOOGLE_CLIENT_ID)
    except ValueError as exc:
        raise UnauthorizedError("Token de Google inválido o expirado") from exc
