"""
Manda por correo el resumen de lotes atrasados a los admins de cada empresa.

    python -m scripts.enviar_alertas

Pensado para correrse una vez al día. Es seguro ejecutarlo de más: cada empresa
recibe como mucho un resumen cada 20 horas, y a las que no tienen atrasos no se
les manda nada (un correo diario diciendo "todo bien" entrena a la gente a
ignorarlos, y entonces tampoco leen el que sí importa).
"""
import logging

from app.db.session import SessionLocal
from app.services.alerta_service import AlertaService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("alertas")


def main() -> None:
    db = SessionLocal()
    try:
        enviados = AlertaService(db).enviar_resumenes_pendientes()
    finally:
        db.close()

    if not enviados:
        logger.info("Ninguna empresa tenía atrasos pendientes de avisar.")
        return

    logger.info("Resumen de atrasos enviado a %s empresa(s): %s", len(enviados), enviados)


if __name__ == "__main__":
    main()
