# app/core/monitoreo.py
"""
Reporte de errores a Sentry.

Sirve para enterarse de que algo falló SIN tener que estar leyendo los logs de
Render a mano. Pero mandar errores a un servicio externo significa mandarles
datos, así que acá lo importante no es conectar Sentry -- eso son tres líneas
-- sino asegurarse de que no se les vaya información de los clientes.
"""
import logging

import sentry_sdk

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cabeceras que jamás deben salir del servidor: llevan credenciales con las
# que alguien podría entrar como el usuario afectado.
_CABECERAS_PROHIBIDAS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-forwarded-for",
    "idempotency-key",
}


def _limpiar(evento: dict, _pista: dict) -> dict | None:
    """Última barrera antes de que un evento salga hacia Sentry.

    El SDK ya viene con `send_default_pii=False`, pero eso no cubre todo:
    esta función quita explícitamente lo que sí sería grave que se filtrara.
    """
    peticion = evento.get("request")
    if peticion:
        # El cuerpo es lo más peligroso: /auth/login, /auth/registro y el
        # cambio de contraseña llevan la contraseña en texto plano. Si Sentry
        # captura el body de una petición que falló, esa contraseña queda
        # guardada en un servicio de terceros.
        peticion.pop("data", None)
        peticion.pop("cookies", None)

        cabeceras = peticion.get("headers") or {}
        peticion["headers"] = {
            nombre: valor
            for nombre, valor in cabeceras.items()
            if nombre.lower() not in _CABECERAS_PROHIBIDAS
        }

        # La query string puede llevar un token de recuperación de contraseña.
        if peticion.get("query_string"):
            peticion["query_string"] = "[omitida]"

    return evento


def configurar_sentry() -> None:
    """Se llama UNA vez, antes de crear la app. Si no hay DSN, no hace nada."""
    if not settings.SENTRY_DSN:
        logger.info("SENTRY_DSN no configurado -- no se reportarán errores a Sentry")
        return

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # Sin esto, Sentry adjunta IP del usuario y datos de sesión a cada
        # evento. No los necesitamos para arreglar un error.
        send_default_pii=False,
        # "never" es lo que impide que se capturen los cuerpos de las
        # peticiones (ver _limpiar). Doble candado a propósito: si alguien
        # cambia esto, el before_send todavía los quita.
        max_request_body_size="never",
        # IMPRESCINDIBLE. Sin esto, Sentry adjunta las variables locales de
        # cada frame del stack trace, y ahí viaja el cuerpo de la petición ya
        # parseado: se comprobó que la contraseña de un login fallido llegaba
        # igual, pese a max_request_body_size="never" y al before_send.
        #
        # Se pierde poder ver el valor de las variables al depurar, pero eso
        # no compensa mandar credenciales de clientes a un tercero. El tipo de
        # error, el archivo y la línea siguen llegando, que es lo que hace
        # falta para arreglarlo.
        include_local_variables=False,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        before_send=_limpiar,
    )
    logger.info("Sentry activo en entorno '%s'", settings.ENVIRONMENT)
