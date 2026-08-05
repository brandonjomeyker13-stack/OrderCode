# app/core/email.py
import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


def enviar_email(destinatario: str, asunto: str, html: str) -> None:
    """
    Envío best-effort vía la API HTTP de Resend (no SMTP: en Render el puerto
    SMTP saliente está bloqueado -- confirmado con un TimeoutError real en
    producción -- pero HTTPS normal sí funciona, igual que la verificación
    de tokens de Google). Si no hay API key o el envío falla, solo se loguea
    -- nunca debe tumbar el flujo de negocio que lo dispara (cambiar
    contraseña, pedir recuperación, etc. deben poder completarse igual).
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY no configurada -- se omite el envío de correo a %s: %s", destinatario, asunto
        )
        return

    try:
        respuesta = requests.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_EMAIL}>",
                "to": [destinatario],
                "subject": asunto,
                "html": html,
            },
            timeout=10,
        )
        respuesta.raise_for_status()
    except Exception:
        logger.exception("Falló el envío de correo a %s", destinatario)
