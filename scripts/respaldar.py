"""
Guarda una copia completa de la base en un archivo JSON.

    python -m scripts.respaldar                    # -> respaldos/respaldo-AAAAMMDD-HHMM.json
    python -m scripts.respaldar ruta/archivo.json  # destino específico

Corre contra la base que apunte DATABASE_URL. Para respaldar producción,
apunta esa variable a Supabase antes de ejecutarlo.

Guarda el archivo resultante FUERA de tu computador (Drive, disco externo,
donde sea): un respaldo que vive en la misma máquina que se puede dañar no
es un respaldo.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.core.respaldo import exportar
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("respaldo")


def main() -> None:
    if len(sys.argv) > 1:
        destino = Path(sys.argv[1])
    else:
        marca = datetime.now().strftime("%Y%m%d-%H%M")
        destino = Path("respaldos") / f"respaldo-{marca}.json"

    db = SessionLocal()
    try:
        conteos = exportar(db, destino)
    finally:
        db.close()

    total = sum(conteos.values())
    logger.info("Respaldo guardado en: %s", destino.resolve())
    logger.info("Filas totales: %s", total)
    for tabla, n in sorted(conteos.items()):
        if n:
            logger.info("  %-28s %s", tabla, n)

    if total == 0:
        logger.warning(
            "\nATENCIÓN: la base está vacía. Verifica que DATABASE_URL apunte "
            "a donde crees que apunta antes de confiar en este archivo."
        )


if __name__ == "__main__":
    main()
