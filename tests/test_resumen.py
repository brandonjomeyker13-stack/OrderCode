# tests/test_resumen.py
"""
Los agregados de los tableros. Lo crítico aquí es que las cifras cuadren con
lo que se calcularía a mano y que NUNCA mezclen datos de otra empresa.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.empresa import Empresa
from app.models.enums import EstadoLote, TipoIncidencia
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService
from app.services.resumen_service import ResumenService


@pytest.fixture
def segundo_taller(db: Session, empresa: Empresa) -> Taller:
    taller = Taller(
        empresa_id=empresa.id, nombre="Taller Dos", numero_taller="T-002", telefono="3007654321"
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


def _asignar(db, empresa, lote, taller, cantidad):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=date(2026, 2, 1),
        ),
    )


def _devolver(db, empresa, asignacion_id, cantidad):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=cantidad, fecha_devolucion=datetime(2026, 2, 5, tzinfo=timezone.utc)
        ),
    )


def _merma(db, empresa, asignacion_id, cantidad):
    return IncidenciaService(db).crear(
        empresa.id,
        IncidenciaCreate(
            asignacion_id=asignacion_id,
            tipo=TipoIncidencia.PRODUCTO_DANADO,
            cantidad_afectada=cantidad,
            descripcion="daño",
            fecha=date(2026, 2, 3),
        ),
    )


# --- Resumen general ---

def test_resumen_de_empresa_sin_movimiento(db: Session, empresa: Empresa):
    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_en_taller == 0
    assert resumen.unidades_devueltas == 0
    assert resumen.unidades_en_merma == 0
    assert resumen.asignaciones_abiertas == 0


def test_las_cifras_cuadran(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """200 asignadas, 50 devueltas, 20 en merma -> quedan 130 en el taller."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _merma(db, empresa, asignacion.id, 20)
    _devolver(db, empresa, asignacion.id, 50)

    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_en_taller == 130
    assert resumen.unidades_devueltas == 50
    assert resumen.unidades_en_merma == 20
    assert resumen.asignaciones_abiertas == 1


def test_una_asignacion_cerrada_no_deja_unidades_en_taller(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 100)

    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_en_taller == 0
    assert resumen.unidades_devueltas == 100
    assert resumen.asignaciones_abiertas == 0


def test_suma_varias_asignaciones(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    _asignar(db, empresa, lote, taller, 100)
    _asignar(db, empresa, lote, segundo_taller, 150)

    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_en_taller == 250
    assert resumen.talleres_activos == 2


def test_cuenta_los_lotes_pendientes_de_asignar(db: Session, empresa: Empresa, lote: Lote):
    resumen = ResumenService(db).general(empresa.id)
    assert resumen.lotes_pendientes_de_asignar == 1


def test_un_lote_ya_asignado_deja_de_estar_pendiente(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 50)

    resumen = ResumenService(db).general(empresa.id)
    assert resumen.lotes_pendientes_de_asignar == 0


def test_el_resumen_no_mezcla_datos_de_otra_empresa(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Lo más grave que podría pasar en un sistema multi-empresa."""
    _asignar(db, empresa, lote, taller, 100)

    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.flush()
    qr = QRCode(empresa_id=otra.id, token="qr-vecino")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=otra.id, nombre="Producto Vecino", referencia="REF-V", qr_code_id=qr.id
    )
    db.add(tipo)
    db.flush()
    lote_vecino = Lote(
        empresa_id=otra.id,
        tipo_producto_id=tipo.id,
        cantidad_total=999,
        fecha_registro=date(2026, 1, 1),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    taller_vecino = Taller(
        empresa_id=otra.id, nombre="Taller Vecino", numero_taller="TV-1", telefono="3001112233"
    )
    db.add_all([lote_vecino, taller_vecino])
    db.commit()
    _asignar(db, otra, lote_vecino, taller_vecino, 900)

    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_en_taller == 100, "se filtraron unidades de otra empresa"
    assert resumen.talleres_activos == 1
    assert resumen.lotes_pendientes_de_asignar == 0


# --- Resumen por taller ---

def test_resumen_por_taller_solo_cuenta_ese_taller(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _merma(db, empresa, asignacion.id, 20)
    _devolver(db, empresa, asignacion.id, 30)
    _asignar(db, empresa, lote, segundo_taller, 100)

    resumen = ResumenService(db).por_taller(taller.id, empresa.id)

    assert resumen.taller.id == taller.id
    assert resumen.unidades_en_taller == 150
    assert resumen.unidades_devueltas == 30
    assert resumen.unidades_en_merma == 20
    assert resumen.total_incidencias == 1
    assert resumen.asignaciones_abiertas == 1
    assert resumen.lotes_en_taller == 1


def test_resumen_de_taller_sin_movimiento(db: Session, empresa: Empresa, taller: Taller):
    resumen = ResumenService(db).por_taller(taller.id, empresa.id)

    assert resumen.unidades_en_taller == 0
    assert resumen.asignaciones_totales == 0
    assert resumen.total_incidencias == 0


def test_resumen_de_taller_inexistente(db: Session, empresa: Empresa):
    with pytest.raises(NotFoundError):
        ResumenService(db).por_taller(99999, empresa.id)


def test_no_se_puede_ver_el_resumen_de_un_taller_ajeno(db: Session, empresa: Empresa):
    """La regla de oro: nunca cruzar el límite de empresa."""
    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.flush()
    taller_ajeno = Taller(
        empresa_id=otra.id, nombre="Ajeno", numero_taller="TA-1", telefono="3009998877"
    )
    db.add(taller_ajeno)
    db.commit()

    with pytest.raises(NotFoundError):
        ResumenService(db).por_taller(taller_ajeno.id, empresa.id)
