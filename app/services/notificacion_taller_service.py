# app/services/notificacion_taller_service.py
import logging

from sqlalchemy.orm import Session

from app.core.pdf import generar_ficha_tecnica
from app.core.whatsapp import enviar_documento_whatsapp
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoNotificacion
from app.models.lote import Lote
from app.models.notificacion_whatsapp import NotificacionWhatsapp
from app.models.taller import Taller
from app.repositories.notificacion_whatsapp_repository import NotificacionWhatsappRepository

logger = logging.getLogger(__name__)


def notificar_asignacion_por_whatsapp(
    db: Session,
    empresa_id: int,
    asignacion: AsignacionTaller,
    lote: Lote,
    taller: Taller,
    empresa_nombre: str,
) -> None:
    """
    Genera la ficha técnica y la manda por WhatsApp al taller, dejando un
    registro del resultado en NotificacionWhatsapp (para poder mostrarlo en
    el front y permitir reenviar si falló). Separado de AsignacionTallerService
    a propósito -- que crear una asignación no dependa de saber cómo se arma
    un PDF o cómo habla con la API de Meta.

    Best-effort de punta a punta: nada de lo que pasa aquí -- ni siquiera un
    fallo al guardar el registro del intento -- debe tumbar el flujo que lo
    dispara (crear la asignación, o el reenvío manual, ya se confirmaron en
    la base de datos antes de llegar aquí).
    """
    try:
        pdf_bytes = generar_ficha_tecnica(
            empresa_nombre=empresa_nombre,
            taller_nombre=taller.nombre,
            taller_numero=taller.numero_taller,
            tipo_producto_nombre=lote.tipo_producto.nombre,
            tipo_producto_referencia=lote.tipo_producto.referencia,
            cantidad_asignada=asignacion.cantidad_asignada,
            fecha_asignacion=asignacion.fecha_asignacion,
            lote_id=lote.id,
            asignacion_id=asignacion.id,
        )
        exito, motivo_error = enviar_documento_whatsapp(
            taller.telefono, pdf_bytes, filename=f"ficha-tecnica-{asignacion.id}.pdf"
        )
    except Exception as exc:
        logger.exception(
            "Falló la generación de la ficha técnica para la asignación %s", asignacion.id
        )
        exito, motivo_error = False, str(exc)[:500]

    try:
        NotificacionWhatsappRepository(db).create(
            NotificacionWhatsapp(
                empresa_id=empresa_id,
                asignacion_id=asignacion.id,
                estado=EstadoNotificacion.ENVIADO if exito else EstadoNotificacion.FALLIDO,
                error=motivo_error,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Falló al registrar el intento de notificación para la asignación %s", asignacion.id
        )
