# app/core/whatsapp.py
import logging
import re

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def _url(path: str) -> str:
    return f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{path}"


def normalizar_telefono(telefono: str) -> str:
    """
    La API de WhatsApp espera el número en formato E.164 sin "+" (solo
    dígitos, con código de país). `Taller.telefono` es texto libre, así que
    aquí se limpia y se antepone el código de país por defecto si no parece
    tenerlo ya -- es una heurística simple (asume que un número que ya
    empieza por el código de país es más largo que uno local), no una
    validación real de formato.
    """
    solo_digitos = re.sub(r"\D", "", telefono)
    if solo_digitos.startswith(settings.WHATSAPP_DEFAULT_COUNTRY_CODE):
        return solo_digitos
    return f"{settings.WHATSAPP_DEFAULT_COUNTRY_CODE}{solo_digitos}"


def _subir_media(pdf_bytes: bytes, filename: str) -> str | None:
    """Sube el PDF al endpoint de media de WhatsApp y devuelve el media_id
    para referenciarlo en el mensaje. None si falla."""
    respuesta = requests.post(
        _url(f"{settings.WHATSAPP_PHONE_NUMBER_ID}/media"),
        headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=15,
    )
    respuesta.raise_for_status()
    return respuesta.json()["id"]


def enviar_documento_whatsapp(telefono: str, pdf_bytes: bytes, filename: str) -> tuple[bool, str | None]:
    """
    Devuelve (éxito, motivo_si_falló) -- nunca lanza. El motivo corto es lo
    que el caller guarda en NotificacionWhatsapp para poder mostrarlo y
    decidir si reintentar; el detalle completo (traceback) siempre queda
    en los logs para debug.

    Requiere una plantilla ya aprobada por Meta con SOLO un header de tipo
    documento (sin variables en el cuerpo) -- ver la explicación de la
    conversación sobre por qué se necesita una plantilla pre-aprobada para
    mensajes que la empresa inicia (no son respuesta a algo que el taller
    escribió primero).
    """
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        motivo = "WhatsApp no está configurado (falta WHATSAPP_ACCESS_TOKEN o WHATSAPP_PHONE_NUMBER_ID)"
        logger.warning("%s -- se omite el envío del documento a %s", motivo, telefono)
        return False, motivo
    if not settings.WHATSAPP_TEMPLATE_NAME:
        motivo = "Falta configurar WHATSAPP_TEMPLATE_NAME"
        logger.warning("%s -- se omite el envío del documento a %s", motivo, telefono)
        return False, motivo

    try:
        media_id = _subir_media(pdf_bytes, filename)

        respuesta = requests.post(
            _url(f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"),
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": normalizar_telefono(telefono),
                "type": "template",
                "template": {
                    "name": settings.WHATSAPP_TEMPLATE_NAME,
                    "language": {"code": settings.WHATSAPP_TEMPLATE_LANGUAGE},
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "document",
                                    "document": {"id": media_id, "filename": filename},
                                }
                            ],
                        }
                    ],
                },
            },
            timeout=15,
        )
        respuesta.raise_for_status()
        return True, None
    except Exception as exc:
        logger.exception("Falló el envío del documento de WhatsApp a %s", telefono)
        return False, str(exc)[:500]
