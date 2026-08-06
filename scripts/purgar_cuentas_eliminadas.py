"""
Borra definitivamente las cuentas cuya ventana de gracia ya venció.

Se corre a mano (o desde un cron, si algún día se monta uno):

    python -m scripts.purgar_cuentas_eliminadas

Es deliberadamente un script y no un endpoint: purgar un tenant completo es
una operación pesada y no debe colgar de la request de ningún usuario. Correrlo
de más es inofensivo -- si ninguna cuenta cumplió el plazo, no hace nada.
"""
import logging

from app.db.session import SessionLocal
from app.services.empresa_service import EmpresaService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("purga")


def main() -> None:
    db = SessionLocal()
    try:
        purgadas = EmpresaService(db).purgar_empresas_vencidas()
    finally:
        db.close()

    if not purgadas:
        logger.info("No hay cuentas que hayan cumplido el plazo de eliminación.")
        return

    logger.info("Cuentas purgadas definitivamente: %s", len(purgadas))
    for empresa_id in purgadas:
        logger.info("  - empresa id %s", empresa_id)


if __name__ == "__main__":
    main()
