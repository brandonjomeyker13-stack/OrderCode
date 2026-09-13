# app/services/notificacion_taller_service.py
import logging
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.core.email import enviar_email
from app.core.pdf import generar_ficha_tecnica
from app.services.corte_service import etiqueta_de
from app.core.whatsapp import enviar_documento_whatsapp
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import CanalNotificacion, EstadoNotificacion
from app.models.lote import Lote
from app.models.notificacion import Notificacion
from app.models.taller import Taller
from app.repositories.notificacion_repository import NotificacionRepository

logger = logging.getLogger(__name__)


def _cuerpo_del_correo(taller: Taller, empresa_nombre: str, asignacion: AsignacionTaller) -> str:
    # escape() sobre lo que escribió el usuario: sin esto, un nombre con "&"
    # o "<" desconfigura el HTML del correo, y alguien podría meter marcado
    # arbitrario en un mensaje que sale a nombre de la plataforma.
    nombre_taller = escape(taller.nombre)
    nombre_empresa = escape(empresa_nombre)
    return f"""
    <p>Hola {nombre_taller},</p>
    <p>{nombre_empresa} te asignó un nuevo lote de producción. Adjuntamos la
    ficha técnica con el detalle de qué recibes, cuánto y desde cuándo.</p>
    <p>Cantidad asignada: <strong>{asignacion.cantidad_asignada}</strong><br>
    Fecha de asignación: {asignacion.fecha_asignacion.strftime('%d/%m/%Y')}</p>
    """


def notificar_asignacion(
    db: Session,
    empresa_id: int,
    asignacion: AsignacionTaller,
    lote: Lote,
    taller: Taller,
    empresa_nombre: str,
) -> None:
    """
    Manda la ficha técnica al taller y deja registro del intento.

    Se intenta WhatsApp primero porque es donde los talleres realmente miran;
    el correo es el respaldo para cuando WhatsApp no está disponible (cuenta
    de Meta sin verificar, número fuera de la lista de prueba, etc.). Si el
    taller no tiene correo cargado, solo queda el registro del fallo.

    Best-effort de punta a punta: NADA de lo que pase acá adentro puede tumbar
    el flujo que lo dispara. Crear la asignación ya se confirmó en la base
    antes de llegar aquí, y no tendría sentido hacerle fallar la operación al
    usuario porque un servicio externo esté caído.
    """
    try:
        _intentar_notificar(db, empresa_id, asignacion, lote, taller, empresa_nombre)
    except Exception:
        # Red de seguridad: los clientes de WhatsApp y correo ya capturan sus
        # propios errores, pero si alguno deja escapar algo inesperado, se
        # queda acá y no sube al caller.
        logger.exception(
            "Falló inesperadamente la notificación de la asignación %s", asignacion.id
        )


def _intentar_notificar(
    db: Session,
    empresa_id: int,
    asignacion: AsignacionTaller,
    lote: Lote,
    taller: Taller,
    empresa_nombre: str,
) -> None:
    filename = f"ficha-tecnica-{asignacion.id}.pdf"
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
            corte=etiqueta_de(lote.corte) if lote.corte else None,
            color=lote.color.nombre if lote.color else None,
        )
    except Exception as exc:
        logger.exception(
            "Falló la generación de la ficha técnica para la asignación %s", asignacion.id
        )
        _registrar(db, empresa_id, asignacion.id, CanalNotificacion.WHATSAPP, False, str(exc)[:500])
        return

    exito, motivo = enviar_documento_whatsapp(taller.telefono, pdf_bytes, filename=filename)
    if exito:
        _registrar(db, empresa_id, asignacion.id, CanalNotificacion.WHATSAPP, True, None)
        return

    if not taller.email:
        logger.warning(
            "WhatsApp falló para la asignación %s y el taller no tiene correo cargado",
            asignacion.id,
        )
        _registrar(db, empresa_id, asignacion.id, CanalNotificacion.WHATSAPP, False, motivo)
        return

    logger.info(
        "WhatsApp falló para la asignación %s, se intenta por correo", asignacion.id
    )
    enviado = enviar_email(
        taller.email,
        f"Nueva asignación de producción de {empresa_nombre}",
        _cuerpo_del_correo(taller, empresa_nombre, asignacion),
        adjunto=(filename, pdf_bytes),
    )
    if enviado:
        # Se guarda el motivo del fallo de WhatsApp igual, para no perder por
        # qué hubo que recurrir al respaldo.
        _registrar(
            db,
            empresa_id,
            asignacion.id,
            CanalNotificacion.CORREO,
            True,
            f"WhatsApp no disponible ({motivo})",
        )
    else:
        _registrar(
            db,
            empresa_id,
            asignacion.id,
            CanalNotificacion.CORREO,
            False,
            f"WhatsApp: {motivo} | Correo: también falló",
        )


def _registrar(
    db: Session,
    empresa_id: int,
    asignacion_id: int,
    canal: CanalNotificacion,
    exito: bool,
    error: str | None,
) -> None:
    try:
        NotificacionRepository(db).create(
            Notificacion(
                empresa_id=empresa_id,
                asignacion_id=asignacion_id,
                canal=canal,
                estado=EstadoNotificacion.ENVIADO if exito else EstadoNotificacion.FALLIDO,
                error=error,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Falló al registrar el intento de notificación para la asignación %s", asignacion_id
        )
