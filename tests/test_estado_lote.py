# tests/test_estado_lote.py
"""
Cómo avanza el estado del LOTE (no el de cada asignación) a medida que los
talleres devuelven.

Importa más de lo que parece: `cerrar_hacia_cliente` solo acepta un lote en
`entregado_completo`, así que un estado de más aquí da por terminado -- y
deja listo para facturar -- trabajo que nunca se hizo.
"""
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.enums import EstadoLote, TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService

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


def _devolver(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=cantidad,
            fecha_devolucion=datetime(2026, 2, 5, tzinfo=timezone.utc),
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


def test_un_lote_a_medio_asignar_no_queda_entregado_completo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Regresión: del lote de 500 se mandan 100 a un taller y el taller las
    devuelve. Esa asignación sí quedó completa, pero 400 unidades no salieron
    nunca de bodega, así que el lote no está entregado."""
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 100)

    db.refresh(lote)
    assert lote.estado == EstadoLote.ENTREGADO_PARCIAL


def test_con_el_lote_entero_asignado_y_devuelto_si_queda_completo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 500)
    _devolver(db, empresa, asignacion.id, 500)

    db.refresh(lote)
    assert lote.estado == EstadoLote.ENTREGADO_COMPLETO


def test_la_merma_cuenta_como_resuelta_para_completar_el_lote(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Las unidades dañadas no vuelven, pero tampoco siguen pendientes en el
    taller: con 400 devueltas y 100 en merma, el lote de 500 está terminado y
    sale de la marca de revisión."""
    asignacion = _asignar(db, empresa, lote, taller, 500)
    _registrar_merma(db, empresa, asignacion.id, 100)
    _devolver(db, empresa, asignacion.id, 400)

    db.refresh(lote)
    assert lote.estado == EstadoLote.ENTREGADO_COMPLETO


def test_una_devolucion_ajena_no_borra_la_marca_de_incidencia(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Regresión: la incidencia deja el lote en revisión para que un admin lo
    mire, y la siguiente devolución de OTRA asignación del mismo lote lo
    bajaba a entregado_parcial. La incidencia se perdía de vista en silencio,
    que es justo lo que IncidenciaService.crear dice querer evitar."""
    con_incidencia = _asignar(db, empresa, lote, taller, 200)
    otra = _asignar(db, empresa, lote, taller, 200)
    _registrar_merma(db, empresa, con_incidencia.id, 20)

    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA

    _devolver(db, empresa, otra.id, 50)

    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA
