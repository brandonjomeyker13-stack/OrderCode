# app/core/email.py
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def enviar_email(destinatario: str, asunto: str, html: str) -> None:
    """
    Envío best-effort: si SMTP no está configurado (típico en desarrollo,
    antes de tener credenciales reales) o el envío falla, solo se loguea --
    nunca debe tumbar el flujo de negocio que lo dispara (cambiar contraseña,
    pedir recuperación, etc. deben poder completarse igual).
    """
    if not settings.SMTP_HOST:
        logger.warning("SMTP no configurado -- se omite el envío de correo a %s: %s", destinatario, asunto)
        return

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    mensaje["To"] = destinatario
    mensaje.set_content("Este correo requiere un cliente compatible con HTML.")
    mensaje.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(mensaje)
    except Exception:
        logger.exception("Falló el envío de correo a %s", destinatario)
