"""
Restaura la base desde un archivo de respaldo.

    python -m scripts.restaurar respaldos/respaldo-20260806-1430.json

DESTRUCTIVO: borra todo lo que haya en la base de destino y la deja
exactamente como el archivo. Pide confirmación escrita antes de tocar nada.

Antes de correrlo, la base debe tener el esquema creado:
    alembic upgrade head
"""
import logging
import sys
from pathlib import Path

from app.core.config import settings
from app.core.respaldo import importar
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("restauracion")

CONFIRMACION = "RESTAURAR"


def _destino_legible() -> str:
    """Muestra a qué base apunta, sin exponer la contraseña en pantalla."""
    url = settings.DATABASE_URL
    if "@" in url:
        return url.split("@", 1)[1]
    return url


def main() -> None:
    if len(sys.argv) < 2:
        logger.error("Uso: python -m scripts.restaurar <archivo.json>")
        sys.exit(1)

    origen = Path(sys.argv[1])
    if not origen.exists():
        logger.error("No existe el archivo: %s", origen)
        sys.exit(1)

    logger.warning("Vas a REEMPLAZAR todo el contenido de esta base:")
    logger.warning("  %s", _destino_legible())
    logger.warning("con el respaldo: %s", origen)
    logger.warning("Todo lo que haya ahora en esa base se pierde.")
    respuesta = input(f'\nEscribe "{CONFIRMACION}" para continuar: ').strip()

    if respuesta != CONFIRMACION:
        logger.info("Cancelado, no se tocó nada.")
        return

    db = SessionLocal()
    try:
        conteos = importar(db, origen)
    finally:
        db.close()

    logger.info("Restauración terminada. Filas escritas: %s", sum(conteos.values()))
    for tabla, n in sorted(conteos.items()):
        if n:
            logger.info("  %-28s %s", tabla, n)


if __name__ == "__main__":
    main()
