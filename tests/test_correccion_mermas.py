# tests/test_correccion_mermas.py
"""
Corrección de mermas por parte de un admin.

Una merma se captura en planta, con prisa y desde el celular. Antes no había
forma de deshacer una mal puesta: esas unidades quedaban restadas para siempre
y el lote se quedaba marcado en revisión sin salida. Un admin ahora puede
corregir la cantidad, descartarla, o decidir que en realidad el taller sí
entregó esas unidades.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.empresa import Empresa
from app.models.enums import EstadoAsignacion, EstadoLote, TipoIncidencia
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate, IncidenciaUpdate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService


def _asignar(db: Session, empresa: Empresa, lote: Lote, taller: Taller, cantidad: int = 100):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=date(2026, 2, 1),
        ),
    )


def _devolver(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=cantidad,
            fecha_devolucion=datetime(2026, 2, 5, tzinfo=timezone.utc),
        ),
    )


def _merma(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int):
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


# --- Corregir ---


def test_corregir_la_cantidad_de_una_merma(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    incidencia = _merma(db, empresa, asignacion.id, 30)

    corregida = IncidenciaService(db).actualizar(
        incidencia.id, empresa.id, IncidenciaUpdate(cantidad_afectada=10)
    )

    assert corregida.cantidad_afectada == 10
    assert corregida.asignacion.cantidad_merma == 10
    # Las 20 unidades que no estaban dañadas vuelven a contar como pendientes
    # en el taller, no al disponible del lote: siguen asignadas.
    assert corregida.asignacion.cantidad_pendiente == 90


def test_no_se_puede_subir_la_merma_por_encima_de_lo_pendiente(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 70)
    incidencia = _merma(db, empresa, asignacion.id, 10)

    # Quedan 30 sin resolver (100 - 70 devueltas), así que 40 es imposible.
    with pytest.raises(ValidationError):
        IncidenciaService(db).actualizar(
            incidencia.id, empresa.id, IncidenciaUpdate(cantidad_afectada=40)
        )


def test_corregir_una_merma_no_la_cuenta_dos_veces(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """El tope tiene que descontar ESTA misma merma. Si no, una asignación que
    está entera en merma tendría pendiente 0 y no se podría ni tocar."""
    asignacion = _asignar(db, empresa, lote, taller)
    incidencia = _merma(db, empresa, asignacion.id, 100)

    corregida = IncidenciaService(db).actualizar(
        incidencia.id, empresa.id, IncidenciaUpdate(tipo=TipoIncidencia.MATERIA_PRIMA_DANADA)
    )

    assert corregida.tipo == TipoIncidencia.MATERIA_PRIMA_DANADA
    assert corregida.cantidad_afectada == 100


# --- Descartar ---


def test_borrar_una_merma_la_deshace_por_completo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    incidencia = _merma(db, empresa, asignacion.id, 100)

    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA

    IncidenciaService(db).eliminar(incidencia.id, empresa.id)

    assert db.get(Incidencia, incidencia.id) is None
    # La asignación vuelve a estar intacta: sin la merma no hay nada resuelto.
    assert db.get(AsignacionTaller, asignacion.id).estado == EstadoAsignacion.ASIGNADO
    db.refresh(lote)
    assert lote.estado == EstadoLote.ASIGNADO_A_TALLER


def test_el_lote_sigue_en_revision_mientras_quede_otra_merma(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    primera = _merma(db, empresa, asignacion.id, 20)
    _merma(db, empresa, asignacion.id, 15)

    IncidenciaService(db).eliminar(primera.id, empresa.id)

    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA


# --- Convertir en entrega del taller ---


def test_convertir_una_merma_en_entrega_del_taller(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    incidencia = _merma(db, empresa, asignacion.id, 40)

    resultado = IncidenciaService(db).convertir_en_devolucion(incidencia.id, empresa.id)

    assert resultado.cantidad_devuelta == 40
    assert resultado.cantidad_merma == 0
    assert resultado.cantidad_pendiente == 60
    assert db.get(Incidencia, incidencia.id) is None

    # Queda como un evento de entrega real, no como un ajuste invisible.
    devoluciones = db.execute(select(Devolucion)).scalars().all()
    assert len(devoluciones) == 1
    assert devoluciones[0].cantidad == 40

    db.refresh(lote)
    assert lote.estado == EstadoLote.ENTREGADO_PARCIAL


def test_convertir_no_altera_el_total_resuelto(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Las unidades solo cambian de columna (merma -> devuelta), así que una
    asignación que ya estaba cerrada sigue cerrada."""
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 60)
    incidencia = _merma(db, empresa, asignacion.id, 40)

    resultado = IncidenciaService(db).convertir_en_devolucion(incidencia.id, empresa.id)

    assert resultado.cantidad_devuelta == 100
    assert resultado.cantidad_merma == 0
    assert resultado.cantidad_pendiente == 0
    assert resultado.estado == EstadoAsignacion.ENTREGADO_COMPLETO
