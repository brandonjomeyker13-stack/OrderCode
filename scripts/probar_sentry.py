"""
Manda un error de prueba a Sentry para comprobar que la conexión funciona.

    python -m scripts.probar_sentry

Usa exactamente la misma configuración que la app (app/core/monitoreo.py), así
que si este error llega a Sentry, los errores reales también van a llegar --
y con la misma limpieza de datos sensibles.

Es un script y no un endpoint a propósito: un endpoint que revienta a
propósito es una puerta abierta en producción, y alguien terminaría
llamándolo sin querer.
"""
import logging

import sentry_sdk

from app.core.config import settings
from app.core.monitoreo import configurar_sentry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("prueba-sentry")


class ErrorDePrueba(Exception):
    """Nombre explícito para que en Sentry se vea de inmediato que no es real."""


def main() -> None:
    if not settings.SENTRY_DSN:
        logger.error(
            "SENTRY_DSN no está configurado, así que no hay nada que probar.\n"
            "Ponlo en el .env (para probar local) o en Render (para probar "
            "producción) y vuelve a ejecutar."
        )
        return

    configurar_sentry()

    logger.info("Entorno: %s", settings.ENVIRONMENT)
    logger.info("Enviando error de prueba...")

    try:
        raise ErrorDePrueba(
            "Prueba de conexión con Sentry -- si ves esto en el panel, funciona. "
            "Puedes marcarlo como resuelto."
        )
    except ErrorDePrueba as exc:
        sentry_sdk.capture_exception(exc)

    # Sin esto el proceso puede terminar antes de que el evento salga.
    enviado = sentry_sdk.flush(timeout=10)

    logger.info("")
    if enviado is False:
        logger.warning(
            "El envío no se confirmó dentro del tiempo de espera. Revisa el DSN "
            "y que haya salida a internet."
        )
    else:
        logger.info("Listo. Revisa el panel de Sentry: debería aparecer un")
        logger.info("evento llamado 'ErrorDePrueba' en unos segundos.")


if __name__ == "__main__":
    main()
