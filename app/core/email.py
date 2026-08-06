# app/core/email.py
import base64
import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


def _armar_payload(
    destinatario: str,
    asunto: str,
    html: str,
    adjunto: tuple[str, bytes] | None,
) -> dict:
    payload = {
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_EMAIL}>",
        "to": [destinatario],
        "subject": asunto,
        "html": html,
    }
    if adjunto is not None:
        filename, contenido = adjunto
        # Resend recibe el archivo en base64 dentro del JSON, no como
        # multipart -- por eso no hace falta armar un MIME a mano.
        payload["attachments"] = [
            {"filename": filename, "content": base64.b64encode(contenido).decode()}
        ]
    return payload


def enviar_email(
    destinatario: str,
    asunto: str,
    html: str,
    adjunto: tuple[str, bytes] | None = None,
) -> bool:
    """
    Envío vía la API HTTP de Resend (no SMTP: en Render el puerto SMTP
    saliente está bloqueado -- confirmado con un TimeoutError real en
    producción -- pero HTTPS normal sí funciona, igual que la verificación
    de tokens de Google).

    `adjunto` es un par (nombre_de_archivo, contenido_en_bytes).

    Devuelve si se envió. Nunca lanza: los flujos que lo llaman (cambiar
    contraseña, pedir recuperación, notificar una asignación) deben poder
    completarse aunque el correo falle.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY no configurada -- se omite el envío de correo a %s: %s",
            destinatario,
            asunto,
        )
        return False

    try:
        respuesta = requests.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json=_armar_payload(destinatario, asunto, html, adjunto),
            timeout=15,
        )
        respuesta.raise_for_status()
        return True
    except Exception:
        logger.exception("Falló el envío de correo a %s", destinatario)
        return False
