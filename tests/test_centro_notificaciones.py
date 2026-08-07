# tests/test_centro_notificaciones.py
"""
Centro de notificaciones (la campanita).

Lo importante: los avisos se derivan del estado real, así que desaparecen
solos cuando el problema se resuelve, y el "leído" se guarda por usuario para
que sobreviva a recargar la página.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario, TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.centro_notificaciones import TipoAviso
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.centro_notificaciones_service import CentroNotificacionesService
from app.services.incidencia_service import IncidenciaService
from tests.conftest import PASSWORD_DE_PRUEBA

RUTA_WHATSAPP = "app.services.notificacion_taller_service.enviar_documento_whatsapp"


def _asignar_hace(db: Session, empresa: Empresa, lote: Lote, taller: Taller, dias: int, cantidad=100):
    with patch(RUTA_WHATSAPP, return_value=(True, None)):
        return AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=lote.id,
                taller_id=taller.id,
                cantidad_asignada=cantidad,
                fecha_asignacion=date.today() - timedelta(days=dias),
            ),
        )


def _tipos(centro) -> list[TipoAviso]:
    return [a.tipo for a in centro.avisos]


# --- Generación de avisos ---

def test_sin_novedades_no_hay_avisos(db: Session, empresa: Empresa, admin: Usuario):
    centro = CentroNotificacionesService(db).listar(empresa.id, admin.id)

    assert centro.total == 0
    assert centro.no_leidas == 0


def test_avisa_de_un_lote_atrasado(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar_hace(db, empresa, lote, taller, dias=30)

    centro = CentroNotificacionesService(db).listar(empresa.id, admin.id)

    assert TipoAviso.LOTE_ATRASADO in _tipos(centro)
    assert centro.no_leidas == 1


def test_avisa_si_no_se_pudo_enviar_la_ficha(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    with patch(RUTA_WHATSAPP, return_value=(False, "API access blocked")):
        AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=lote.id, taller_id=taller.id, cantidad_asignada=50,
                fecha_asignacion=date.today(),
            ),
        )

    centro = CentroNotificacionesService(db).listar(empresa.id, admin.id)
    assert TipoAviso.ENVIO_FALLIDO in _tipos(centro)


def test_un_reenvio_exitoso_quita_el_aviso(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """El aviso mira el ÚLTIMO intento: si ya se reenvió bien, no debe seguir
    apareciendo como problema."""
    with patch(RUTA_WHATSAPP, return_value=(False, "fallo")):
        asignacion = AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=lote.id, taller_id=taller.id, cantidad_asignada=50,
                fecha_asignacion=date.today(),
            ),
        )
    with patch(RUTA_WHATSAPP, return_value=(True, None)):
        AsignacionTallerService(db).reenviar_notificacion(asignacion.id, empresa.id)

    centro = CentroNotificacionesService(db).listar(empresa.id, admin.id)
    assert TipoAviso.ENVIO_FALLIDO not in _tipos(centro)


def test_avisa_de_una_incidencia_reciente(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    asignacion = _asignar_hace(db, empresa, lote, taller, dias=1)
    IncidenciaService(db).crear(
        empresa.id,
        IncidenciaCreate(
            asignacion_id=asignacion.id,
            tipo=TipoIncidencia.PRODUCTO_DANADO,
            cantidad_afectada=10,
            descripcion="Prendas manchadas",
            fecha=date.today(),
        ),
    )

    centro = CentroNotificacionesService(db).listar(empresa.id, admin.id)
    assert TipoAviso.INCIDENCIA in _tipos(centro)


def test_el_aviso_desaparece_cuando_se_resuelve(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """La razón de calcular los avisos en vez de guardarlos: si el taller
    entrega, el aviso de atraso se va solo, sin limpiar nada."""
    asignacion = _asignar_hace(db, empresa, lote, taller, dias=30)
    servicio = CentroNotificacionesService(db)
    assert TipoAviso.LOTE_ATRASADO in _tipos(servicio.listar(empresa.id, admin.id))

    AsignacionTallerService(db).registrar_devolucion(
        asignacion.id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=100, fecha_devolucion=datetime.now(timezone.utc)
        ),
    )

    assert TipoAviso.LOTE_ATRASADO not in _tipos(servicio.listar(empresa.id, admin.id))


def test_no_muestra_avisos_de_otra_empresa(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar_hace(db, empresa, lote, taller, dias=30)
    otra = Empresa(nombre="Vecina", activo=True)
    db.add(otra)
    db.commit()

    assert CentroNotificacionesService(db).listar(otra.id, admin.id).total == 0


# --- Estado de leído ---

def test_marcar_leida_persiste(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """El problema que había: al recargar volvían a salir como no leídas."""
    _asignar_hace(db, empresa, lote, taller, dias=30)
    servicio = CentroNotificacionesService(db)
    aviso = servicio.listar(empresa.id, admin.id).avisos[0]

    servicio.marcar_leida(admin.id, aviso.id)

    centro = servicio.listar(empresa.id, admin.id)
    assert centro.avisos[0].leida is True
    assert centro.no_leidas == 0


def test_marcar_leida_es_idempotente(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar_hace(db, empresa, lote, taller, dias=30)
    servicio = CentroNotificacionesService(db)
    aviso = servicio.listar(empresa.id, admin.id).avisos[0]

    servicio.marcar_leida(admin.id, aviso.id)
    servicio.marcar_leida(admin.id, aviso.id)

    assert servicio.listar(empresa.id, admin.id).no_leidas == 0


def test_leer_todas(db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller):
    _asignar_hace(db, empresa, lote, taller, dias=30, cantidad=50)
    _asignar_hace(db, empresa, lote, taller, dias=40, cantidad=50)
    servicio = CentroNotificacionesService(db)
    assert servicio.listar(empresa.id, admin.id).no_leidas == 2

    servicio.marcar_todas_leidas(empresa.id, admin.id)

    assert servicio.listar(empresa.id, admin.id).no_leidas == 0


def test_lo_leido_es_por_usuario(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Que el dueño lea un aviso no debe marcarlo como visto para su equipo."""
    _asignar_hace(db, empresa, lote, taller, dias=30)
    otro = Usuario(
        empresa_id=empresa.id,
        nombre="Operario",
        email="operario@prueba.com",
        password_hash=hash_password(PASSWORD_DE_PRUEBA),
        rol=RolUsuario.OPERADOR,
    )
    db.add(otro)
    db.commit()

    servicio = CentroNotificacionesService(db)
    servicio.marcar_leida(admin.id, servicio.listar(empresa.id, admin.id).avisos[0].id)

    assert servicio.listar(empresa.id, admin.id).no_leidas == 0
    assert servicio.listar(empresa.id, otro.id).no_leidas == 1


def test_un_aviso_nuevo_llega_sin_leer(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    _asignar_hace(db, empresa, lote, taller, dias=30, cantidad=50)
    servicio = CentroNotificacionesService(db)
    servicio.marcar_todas_leidas(empresa.id, admin.id)

    _asignar_hace(db, empresa, lote, taller, dias=45, cantidad=50)

    assert servicio.listar(empresa.id, admin.id).no_leidas == 1
