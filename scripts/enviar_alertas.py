"""
Manda por correo el resumen de lotes atrasados a los admins de cada empresa.

    python -m scripts.enviar_alertas

Pensado para correrse una vez al día. Es seguro ejecutarlo de más: cada empresa
recibe como mucho un resumen cada 20 horas, y a las que no tienen atrasos no se
les manda nada (un correo diario diciendo "todo bien" entrena a la gente a
ignorarlos, y entonces tampoco leen el que sí importa).

Corre desatendido desde el Programador de tareas (ver alertas.bat), así que
devuelve código de salida 1 si algo falla: si no, un error dejaría a los
clientes sin sus avisos y nadie se enteraría hasta que alguien reclamara.

Ojo: "ninguna empresa tenía atrasos" NO es un fallo. Es el caso normal cuando
todo va al día, y por eso devuelve cero.
"""
import logging
import sys

from app.db.session import SessionLocal
from app.services.alerta_service import AlertaService

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("alertas")


def main() -> int:
    db = SessionLocal()
    try:
        enviados = AlertaService(db).enviar_resumenes_pendientes()
    except Exception:
        logger.exception("Falló el envío de alertas")
        return 1
    finally:
        db.close()

    if not enviados:
        logger.info("Ninguna empresa tenía atrasos pendientes de avisar.")
        return 0

    logger.info("Resumen de atrasos enviado a %s empresa(s): %s", len(enviados), enviados)
    return 0


if __name__ == "__main__":
    sys.exit(main())
