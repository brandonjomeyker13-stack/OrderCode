# tests/test_produccion.py
"""
Reglas de negocio del flujo de producción: cuánto se puede asignar, cómo se
acumulan las devoluciones, y cómo la merma (unidades dañadas) NO devuelve
stock pero sí cierra la asignación.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models.empresa import Empresa
from app.models.enums import EstadoAsignacion, TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService
from app.services.lote_service import LoteService

FECHA_ASIGNACION = date(2026, 2, 1)


def _asignar(db: Session, empresa: Empresa, lote: Lote, taller: Taller, cantidad: int):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=FECHA_ASIGNACION,
        ),
    )


def _devolver(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int, dia: int = 5):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=cantidad,
            fecha_devolucion=datetime(2026, 2, dia, tzinfo=timezone.utc),
        ),
    )


def _registrar_merma(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int):
    return IncidenciaService(db).crear(
        empresa.id,
        IncidenciaCreate(
            asignacion_id=asignacion_id,
            tipo=TipoIncidencia.PRODUCTO_DANADO,
            cantidad_afectada=cantidad,
            descripcion="prendas dañadas en el taller",
            fecha=date(2026, 2, 3),
        ),
    )


# --- Disponibilidad del lote ---

def test_no_se_puede_asignar_mas_de_lo_disponible(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    with pytest.raises(ValidationError):
        _asignar(db, empresa, lote, taller, lote.cantidad_total + 1)


def test_asignar_descuenta_del_disponible(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    _asignar(db, empresa, lote, taller, 200)

    vista = LoteService(db).obtener_con_disponibilidad(lote.id, empresa.id)
    assert vista.cantidad_asignada_total == 200
    assert vista.cantidad_disponible == 300


# --- Devoluciones ---

def test_las_devoluciones_se_acumulan(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """Un taller entrega por tandas: la segunda devolución suma sobre la
    primera, no la reemplaza."""
    asignacion = _asignar(db, empresa, lote, taller, 200)

    _devolver(db, empresa, asignacion.id, 80, dia=5)
    resultado = _devolver(db, empresa, asignacion.id, 50, dia=6)

    assert resultado.cantidad_devuelta == 130
    assert resultado.cantidad_pendiente == 70
    assert resultado.estado == EstadoAsignacion.ENTREGADO_PARCIAL


def test_devolver_todo_cierra_la_asignacion(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)

    resultado = _devolver(db, empresa, asignacion.id, 100)

    assert resultado.estado == EstadoAsignacion.ENTREGADO_COMPLETO
    assert resultado.cantidad_pendiente == 0


def test_no_se_puede_devolver_mas_de_lo_asignado(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)

    with pytest.raises(ValidationError):
        _devolver(db, empresa, asignacion.id, 101)


# --- Fechas ---

def test_no_se_puede_devolver_antes_de_la_entrega(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Si el taller recibió el 1 de febrero, es imposible que haya devuelto
    el 31 de enero."""
    asignacion = _asignar(db, empresa, lote, taller, 100)

    with pytest.raises(ValidationError):
        AsignacionTallerService(db).registrar_devolucion(
            asignacion.id,
            empresa.id,
            AsignacionTallerRegistrarDevolucion(
                cantidad_devuelta=10,
                fecha_devolucion=datetime(2026, 1, 31, tzinfo=timezone.utc),
            ),
        )


def test_no_se_puede_devolver_antes_de_la_ultima_devolucion(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 50, dia=10)

    with pytest.raises(ValidationError):
        _devolver(db, empresa, asignacion.id, 50, dia=8)


# --- Merma (unidades dañadas) ---

def test_la_merma_no_devuelve_stock_al_lote(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Lo dañado se perdió: no vuelve a estar disponible para reasignar."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    disponible_antes = LoteService(db).obtener_con_disponibilidad(
        lote.id, empresa.id
    ).cantidad_disponible

    _registrar_merma(db, empresa, asignacion.id, 20)

    disponible_despues = LoteService(db).obtener_con_disponibilidad(
        lote.id, empresa.id
    ).cantidad_disponible
    assert disponible_despues == disponible_antes


def test_la_merma_baja_lo_pendiente_del_taller(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Lo dañado ya no está "en poder del taller", así que no puede seguir
    contando como pendiente de entrega."""
    asignacion = _asignar(db, empresa, lote, taller, 200)

    _registrar_merma(db, empresa, asignacion.id, 20)

    vista = AsignacionTallerService(db).obtener_con_merma(asignacion.id, empresa.id)
    assert vista.cantidad_merma == 20
    assert vista.cantidad_pendiente == 180


def test_devolucion_mas_merma_cierra_la_asignacion(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)

    _registrar_merma(db, empresa, asignacion.id, 20)
    resultado = _devolver(db, empresa, asignacion.id, 80)

    assert resultado.estado == EstadoAsignacion.ENTREGADO_COMPLETO
    assert resultado.cantidad_pendiente == 0


def test_no_se_puede_devolver_lo_que_esta_en_merma(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Las unidades dañadas no se pueden entregar como buenas."""
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _registrar_merma(db, empresa, asignacion.id, 20)

    with pytest.raises(ValidationError):
        _devolver(db, empresa, asignacion.id, 90)


def test_la_merma_no_puede_exceder_lo_pendiente(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 90)

    with pytest.raises(ValidationError):
        _registrar_merma(db, empresa, asignacion.id, 20)
