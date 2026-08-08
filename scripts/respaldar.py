"""
Guarda una copia completa de la base en un archivo JSON.

    python -m scripts.respaldar                    # -> respaldos/respaldo-AAAAMMDD-HHMM.json
    python -m scripts.respaldar ruta/archivo.json  # destino específico

Corre contra la base que apunte DATABASE_URL. Para respaldar producción,
apunta esa variable a Supabase antes de ejecutarlo.

Guarda el archivo resultante FUERA de tu computador (Drive, disco externo,
donde sea): un respaldo que vive en la misma máquina que se puede dañar no
es un respaldo.

Pensado para correr desatendido (ver respaldar.bat y el Programador de
tareas de Windows): devuelve código de salida 1 si algo sale mal, para que
la tarea programada quede marcada como fallida en vez de fallar en silencio.
"""
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from app.core.respaldo import exportar
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("respaldo")

# Cuántos respaldos se conservan en la carpeta. Con una tarea diaria, un mes
# de historial es suficiente para volver atrás si un daño pasó inadvertido
# varios días, sin llenar el disco.
CONSERVAR = 30

# Exactamente el formato que genera este script: respaldo-AAAAMMDD-HHMM.json.
# Es una expresión regular y no un comodín tipo "respaldo-*.json" porque ese
# comodín también atrapa lo que el usuario guarde a mano -- un
# "respaldo-importante.json" entraría al conteo, y peor, al ordenar
# alfabéticamente quedaría después de las fechas y haría que se borrara un
# respaldo real en su lugar.
_PATRON = re.compile(r"^respaldo-\d{8}-\d{4}\.json$")


def _rotar(carpeta: Path, conservar: int = CONSERVAR) -> list[Path]:
    """Borra los respaldos más viejos y devuelve los que borró.

    Solo toca archivos que coincidan exactamente con el patrón de nombre que
    genera este script. Cualquier otra cosa que haya en la carpeta se queda
    donde está: es una función que BORRA, así que se limita a lo que ella
    misma creó.

    El nombre lleva la fecha en formato AAAAMMDD-HHMM, que ordena
    alfabéticamente igual que cronológicamente. Se ordena por nombre y no
    por fecha del archivo porque copiar o mover archivos altera esa fecha.
    """
    if conservar < 1:
        return []

    archivos = sorted(p for p in carpeta.glob("*.json") if _PATRON.match(p.name))
    sobrantes = archivos[:-conservar] if len(archivos) > conservar else []

    borrados = []
    for archivo in sobrantes:
        try:
            archivo.unlink()
            borrados.append(archivo)
        except OSError as exc:
            # Que no se pueda borrar uno viejo no invalida el respaldo nuevo.
            logger.warning("No se pudo borrar %s: %s", archivo.name, exc)
    return borrados


def main() -> int:
    destino_propio = len(sys.argv) > 1
    if destino_propio:
        destino = Path(sys.argv[1])
    else:
        marca = datetime.now().strftime("%Y%m%d-%H%M")
        destino = Path("respaldos") / f"respaldo-{marca}.json"

    db = SessionLocal()
    try:
        conteos = exportar(db, destino)
    except Exception:
        logger.exception("El respaldo FALLÓ y no se generó ningún archivo")
        return 1
    finally:
        db.close()

    total = sum(conteos.values())
    logger.info("Respaldo guardado en: %s", destino.resolve())
    logger.info("Filas totales: %s", total)
    for tabla, n in sorted(conteos.items()):
        if n:
            logger.info("  %-28s %s", tabla, n)

    if total == 0:
        logger.error(
            "\nATENCIÓN: la base está vacía. Verifica que DATABASE_URL apunte "
            "a donde crees que apunta antes de confiar en este archivo."
        )
        # Se devuelve error a propósito: un respaldo vacío es peor que
        # ninguno, porque da una falsa sensación de seguridad.
        return 1

    # La rotación solo aplica a la carpeta que administra este script. Si
    # alguien pidió un destino específico, no se le tocan sus archivos.
    if not destino_propio:
        borrados = _rotar(destino.parent)
        if borrados:
            logger.info(
                "Se borraron %s respaldo(s) viejos, conservando los %s más recientes.",
                len(borrados),
                CONSERVAR,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
