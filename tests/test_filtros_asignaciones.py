# tests/test_filtros_asignaciones.py
"""
Filtros del listado de asignaciones. Además de que filtren bien, importa que
el conteo (X-Total-Count) refleje lo filtrado y que ningún filtro permita ver
datos de otra empresa.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.enums import EstadoAsignacion, EstadoLote
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.filtros import FiltrosAsignacion
from app.services.asignacion_taller_service import AsignacionTallerService

SIN_LIMITE = 100


@pytest.fixture
def segundo_taller(db: Session, empresa: Empresa) -> Taller:
    taller = Taller(
        empresa_id=empresa.id, nombre="Taller Dos", numero_taller="T-002", telefono="3007654321"
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


@pytest.fixture
def segundo_lote(db: Session, empresa: Empresa, lote: Lote) -> Lote:
    otro = Lote(
        empresa_id=empresa.id,
        tipo_producto_id=lote.tipo_producto_id,
        cantidad_total=300,
        fecha_registro=date(2026, 1, 10),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    db.add(otro)
    db.commit()
    db.refresh(otro)
    return otro


def _asignar(db, empresa, lote, taller, cantidad, dia):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=date(2026, 2, dia),
        ),
    )


def test_sin_filtros_devuelve_todo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    _asignar(db, empresa, lote, taller, 50, 1)
    _asignar(db, empresa, lote, segundo_taller, 50, 2)

    servicio = AsignacionTallerService(db)
    assert len(servicio.listar(empresa.id, 0, SIN_LIMITE)) == 2
    assert servicio.contar(empresa.id) == 2


def test_filtra_por_taller(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    _asignar(db, empresa, lote, taller, 50, 1)
    _asignar(db, empresa, lote, segundo_taller, 60, 2)

    filtros = FiltrosAsignacion(taller_id=taller.id)
    servicio = AsignacionTallerService(db)
    resultado = servicio.listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert len(resultado) == 1
    assert resultado[0].taller.id == taller.id
    assert servicio.contar(empresa.id, filtros) == 1


def test_filtra_por_lote(
    db: Session, empresa: Empresa, lote: Lote, segundo_lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 50, 1)
    _asignar(db, empresa, segundo_lote, taller, 60, 2)

    filtros = FiltrosAsignacion(lote_id=segundo_lote.id)
    resultado = AsignacionTallerService(db).listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert len(resultado) == 1
    assert resultado[0].lote_id == segundo_lote.id


def test_filtra_por_estado(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    abierta = _asignar(db, empresa, lote, taller, 50, 1)
    cerrada = _asignar(db, empresa, lote, segundo_taller, 60, 2)
    AsignacionTallerService(db).registrar_devolucion(
        cerrada.id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=60, fecha_devolucion=datetime(2026, 2, 10, tzinfo=timezone.utc)
        ),
    )

    servicio = AsignacionTallerService(db)
    filtros = FiltrosAsignacion(estado=EstadoAsignacion.ASIGNADO)
    resultado = servicio.listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert [a.id for a in resultado] == [abierta.id]
    assert servicio.contar(empresa.id, filtros) == 1


def test_filtra_por_rango_de_fechas(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    _asignar(db, empresa, lote, taller, 10, 1)
    del_medio = _asignar(db, empresa, lote, taller, 10, 15)
    _asignar(db, empresa, lote, taller, 10, 28)

    servicio = AsignacionTallerService(db)
    filtros = FiltrosAsignacion(desde=date(2026, 2, 10), hasta=date(2026, 2, 20))
    resultado = servicio.listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert [a.id for a in resultado] == [del_medio.id]


def test_las_fechas_son_inclusivas(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    justo = _asignar(db, empresa, lote, taller, 10, 15)

    filtros = FiltrosAsignacion(desde=date(2026, 2, 15), hasta=date(2026, 2, 15))
    resultado = AsignacionTallerService(db).listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert [a.id for a in resultado] == [justo.id]


def test_los_filtros_se_combinan(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    esperada = _asignar(db, empresa, lote, taller, 10, 15)
    _asignar(db, empresa, lote, segundo_taller, 10, 15)
    _asignar(db, empresa, lote, taller, 10, 28)

    filtros = FiltrosAsignacion(taller_id=taller.id, desde=date(2026, 2, 10), hasta=date(2026, 2, 20))
    resultado = AsignacionTallerService(db).listar(empresa.id, 0, SIN_LIMITE, filtros)

    assert [a.id for a in resultado] == [esperada.id]


def test_el_conteo_respeta_los_filtros(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    """Si el total no coincide con lo filtrado, la paginación del front
    muestra páginas vacías."""
    _asignar(db, empresa, lote, taller, 10, 1)
    _asignar(db, empresa, lote, segundo_taller, 10, 2)
    _asignar(db, empresa, lote, segundo_taller, 10, 3)

    servicio = AsignacionTallerService(db)
    filtros = FiltrosAsignacion(taller_id=segundo_taller.id)

    assert servicio.contar(empresa.id) == 3
    assert servicio.contar(empresa.id, filtros) == 2


def test_un_filtro_no_permite_ver_otra_empresa(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """Pedir explícitamente el taller de otra empresa no debe devolver nada."""
    otra = Empresa(nombre="Vecina", activo=True)
    db.add(otra)
    db.flush()
    qr = QRCode(empresa_id=otra.id, token="qr-v")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(empresa_id=otra.id, nombre="PV", referencia="RV", qr_code_id=qr.id)
    db.add(tipo)
    db.flush()
    lote_ajeno = Lote(
        empresa_id=otra.id,
        tipo_producto_id=tipo.id,
        cantidad_total=100,
        fecha_registro=date(2026, 1, 1),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    taller_ajeno = Taller(
        empresa_id=otra.id, nombre="Ajeno", numero_taller="TA", telefono="3000000000"
    )
    db.add_all([lote_ajeno, taller_ajeno])
    db.commit()
    _asignar(db, otra, lote_ajeno, taller_ajeno, 50, 1)

    servicio = AsignacionTallerService(db)
    filtros = FiltrosAsignacion(taller_id=taller_ajeno.id)

    assert servicio.listar(empresa.id, 0, SIN_LIMITE, filtros) == []
    assert servicio.contar(empresa.id, filtros) == 0
