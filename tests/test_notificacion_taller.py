# tests/test_notificacion_taller.py
"""
Envío de la ficha técnica al taller: WhatsApp primero, correo como respaldo.

Se mockean los dos canales para no depender de servicios externos: lo que se
prueba es la lógica de decisión y el registro del resultado, no que Meta o
Resend funcionen.
"""
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.enums import CanalNotificacion, EstadoNotificacion
from app.models.lote import Lote
from app.models.notificacion import Notificacion
from app.models.taller import Taller
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.services.asignacion_taller_service import AsignacionTallerService

RUTA_WHATSAPP = "app.services.notificacion_taller_service.enviar_documento_whatsapp"
RUTA_CORREO = "app.services.notificacion_taller_service.enviar_email"


@pytest.fixture
def taller_con_correo(db: Session, empresa: Empresa) -> Taller:
    taller = Taller(
        empresa_id=empresa.id,
        nombre="Taller Con Correo",
        numero_taller="T-900",
        telefono="3001112233",
        email="taller@ejemplo.com",
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


def _asignar(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=50,
            fecha_asignacion=date(2026, 2, 1),
        ),
    )


def _notificar(db: Session, empresa: Empresa, asignacion):
    return AsignacionTallerService(db).reenviar_notificacion(asignacion.id, empresa.id)


def _notificaciones(db: Session) -> list[Notificacion]:
    return list(db.execute(select(Notificacion)).scalars().all())


def test_si_whatsapp_funciona_no_se_manda_correo(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    """El correo es respaldo, no duplicado: molestar por dos canales a la vez
    haría que el taller deje de mirarlos."""
    with patch(RUTA_WHATSAPP, return_value=(True, None)), patch(RUTA_CORREO) as correo:
        asignacion = _asignar(db, empresa, lote, taller_con_correo)
        _notificar(db, empresa, asignacion)

    correo.assert_not_called()
    registro = _notificaciones(db)[0]
    assert registro.canal == CanalNotificacion.WHATSAPP
    assert registro.estado == EstadoNotificacion.ENVIADO


def test_si_whatsapp_falla_se_manda_por_correo(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    with patch(RUTA_WHATSAPP, return_value=(False, "API access blocked")), patch(
        RUTA_CORREO, return_value=True
    ) as correo:
        asignacion = _asignar(db, empresa, lote, taller_con_correo)
        _notificar(db, empresa, asignacion)

    correo.assert_called_once()
    assert correo.call_args.args[0] == "taller@ejemplo.com"

    registro = _notificaciones(db)[0]
    assert registro.canal == CanalNotificacion.CORREO
    assert registro.estado == EstadoNotificacion.ENVIADO
    # No se pierde por qué hubo que usar el respaldo.
    assert "API access blocked" in registro.error


def test_el_correo_lleva_el_pdf_adjunto(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    with patch(RUTA_WHATSAPP, return_value=(False, "fallo")), patch(
        RUTA_CORREO, return_value=True
    ) as correo:
        asignacion = _asignar(db, empresa, lote, taller_con_correo)
        _notificar(db, empresa, asignacion)

    nombre_archivo, contenido = correo.call_args.kwargs["adjunto"]
    assert nombre_archivo == f"ficha-tecnica-{asignacion.id}.pdf"
    assert contenido.startswith(b"%PDF-"), "el adjunto no es un PDF válido"


def test_sin_correo_cargado_solo_queda_el_fallo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """El taller del fixture no tiene correo: no hay respaldo posible."""
    with patch(RUTA_WHATSAPP, return_value=(False, "API access blocked")), patch(
        RUTA_CORREO
    ) as correo:
        asignacion = _asignar(db, empresa, lote, taller)
        _notificar(db, empresa, asignacion)

    correo.assert_not_called()
    registro = _notificaciones(db)[0]
    assert registro.canal == CanalNotificacion.WHATSAPP
    assert registro.estado == EstadoNotificacion.FALLIDO


def test_si_fallan_los_dos_queda_registrado(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    with patch(RUTA_WHATSAPP, return_value=(False, "whatsapp caido")), patch(
        RUTA_CORREO, return_value=False
    ):
        asignacion = _asignar(db, empresa, lote, taller_con_correo)
        _notificar(db, empresa, asignacion)

    registro = _notificaciones(db)[0]
    assert registro.estado == EstadoNotificacion.FALLIDO
    assert "whatsapp caido" in registro.error


def test_asignar_no_manda_la_ficha(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    """La ficha se imprime. Mandarla por WhatsApp o correo ya no es del flujo."""
    with patch(RUTA_WHATSAPP) as whatsapp, patch(RUTA_CORREO) as correo:
        _asignar(db, empresa, lote, taller_con_correo)

    whatsapp.assert_not_called()
    correo.assert_not_called()
    assert _notificaciones(db) == []


def test_la_asignacion_se_crea_aunque_fallen_los_dos_canales(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    """Lo más importante: notificar es best-effort y nunca puede tumbar el
    registro de la producción."""
    asignacion = _asignar(db, empresa, lote, taller_con_correo)
    with patch(RUTA_WHATSAPP, side_effect=RuntimeError("caída total")), patch(RUTA_CORREO):
        _notificar(db, empresa, asignacion)

    assert asignacion.id is not None
    assert asignacion.cantidad_asignada == 50


def test_el_reenvio_actualiza_el_canal(
    db: Session, empresa: Empresa, lote: Lote, taller_con_correo: Taller
):
    """Si el primer intento salió por correo y luego WhatsApp ya funciona, la
    asignación debe reflejar el canal del último intento."""
    with patch(RUTA_WHATSAPP, return_value=(False, "fallo")), patch(RUTA_CORREO, return_value=True):
        asignacion = _asignar(db, empresa, lote, taller_con_correo)
        asignacion = _notificar(db, empresa, asignacion)
    assert asignacion.canal_notificacion == CanalNotificacion.CORREO

    servicio = AsignacionTallerService(db)
    with patch(RUTA_WHATSAPP, return_value=(True, None)):
        resultado = servicio.reenviar_notificacion(asignacion.id, empresa.id)

    assert resultado.notificacion_enviada is True
    assert resultado.canal_notificacion == CanalNotificacion.WHATSAPP
