# tests/test_devoluciones_historial.py
"""
Historial de devoluciones como eventos.

Antes solo se guardaba el acumulado por asignación y la fecha de la última
entrega, así que el detalle de cada tanda se perdía y "devueltas hoy" salía
inflado. Estos tests fijan el comportamiento correcto.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models.devolucion import Devolucion
from app.models.empresa import Empresa
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.resumen_service import ResumenService

HOY = datetime.now(timezone.utc)
AYER = HOY - timedelta(days=1)


def _asignar(db: Session, empresa: Empresa, lote: Lote, taller: Taller, cantidad=200):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=date(2026, 1, 1),
        ),
    )


def _devolver(db: Session, empresa: Empresa, asignacion_id: int, cantidad: int, cuando: datetime):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(cantidad_devuelta=cantidad, fecha_devolucion=cuando),
    )


def test_cada_entrega_queda_como_evento_propio(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 50, AYER)
    _devolver(db, empresa, asignacion.id, 30, HOY)

    eventos = db.execute(select(Devolucion).order_by(Devolucion.fecha)).scalars().all()
    assert [e.cantidad for e in eventos] == [50, 30]


def test_el_acumulado_sigue_cuadrando(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """Los eventos son la fuente de verdad, pero el acumulado denormalizado
    tiene que seguir coincidiendo con su suma."""
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 50, AYER)
    resultado = _devolver(db, empresa, asignacion.id, 30, HOY)

    eventos = db.execute(select(Devolucion)).scalars().all()
    assert resultado.cantidad_devuelta == sum(e.cantidad for e in eventos) == 80


def test_la_asignacion_expone_su_historial(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 50, AYER)
    resultado = _devolver(db, empresa, asignacion.id, 30, HOY)

    assert [d.cantidad for d in resultado.devoluciones] == [50, 30]


def test_devueltas_hoy_no_cuenta_lo_de_ayer(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """El caso exacto que antes daba mal: con solo el acumulado, un taller que
    devolvió 50 ayer y 30 hoy reportaba 80 como "devuelto hoy"."""
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 50, AYER)
    _devolver(db, empresa, asignacion.id, 30, HOY)

    resumen = ResumenService(db).general(empresa.id)

    assert resumen.unidades_devueltas_hoy == 30
    assert resumen.unidades_devueltas == 80


def test_sin_devoluciones_hoy_da_cero(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 50, AYER)

    assert ResumenService(db).general(empresa.id).unidades_devueltas_hoy == 0


def test_devueltas_hoy_no_mezcla_otras_empresas(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller)
    _devolver(db, empresa, asignacion.id, 40, HOY)

    otra = Empresa(nombre="Vecina", activo=True)
    db.add(otra)
    db.commit()

    assert ResumenService(db).general(otra.id).unidades_devueltas_hoy == 0


def test_el_listado_no_dispara_una_consulta_por_fila(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Regresión: exponer las devoluciones en la salida reintrodujo un N+1
    (una consulta extra por asignación al leer la relación)."""
    for _ in range(10):
        asignacion = _asignar(db, empresa, lote, taller, cantidad=10)
        _devolver(db, empresa, asignacion.id, 5, HOY)
    db.expire_all()

    conteo = {"n": 0}
    motor = db.get_bind()

    @event.listens_for(motor, "before_cursor_execute")
    def contar(conn, cursor, stmt, params, ctx, many):
        conteo["n"] += 1

    try:
        AsignacionTallerService(db).listar(empresa.id, 0, 10)
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    # Un puñado de consultas en bloque, no una por fila.
    assert conteo["n"] < 10, f"parece un N+1: {conteo['n']} consultas para 10 filas"
