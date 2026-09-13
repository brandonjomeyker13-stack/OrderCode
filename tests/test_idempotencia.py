# tests/test_idempotencia.py
"""
Protección contra doble clic: mandar la misma operación dos veces con la
misma Idempotency-Key no debe duplicar nada.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.empresa import Empresa
from app.models.enums import TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.schemas.corte import CorteCreate, LineaCorteCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService
from app.services.corte_service import CorteService

CLAVE = "clave-de-idempotencia-123"


def _datos_asignacion(lote: Lote, taller: Taller) -> AsignacionTallerCreate:
    return AsignacionTallerCreate(
        lote_id=lote.id, taller_id=taller.id, cantidad_asignada=100, fecha_asignacion=date(2026, 2, 1)
    )


def test_doble_clic_no_duplica_la_asignacion(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    servicio = AsignacionTallerService(db)
    datos = _datos_asignacion(lote, taller)

    primera = servicio.crear(empresa.id, datos, idempotency_key=CLAVE)
    segunda = servicio.crear(empresa.id, datos, idempotency_key=CLAVE)

    assert primera.id == segunda.id
    creadas = db.execute(select(AsignacionTaller)).scalars().all()
    assert len(creadas) == 1


def test_sin_clave_si_se_crean_dos(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """La idempotencia es opt-in: sin la cabecera, dos llamadas iguales son
    dos asignaciones reales (puede ser intencional mandar dos tandas)."""
    servicio = AsignacionTallerService(db)
    datos = _datos_asignacion(lote, taller)

    servicio.crear(empresa.id, datos)
    servicio.crear(empresa.id, datos)

    assert len(db.execute(select(AsignacionTaller)).scalars().all()) == 2


def test_reusar_la_clave_en_otra_ruta_se_rechaza(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Regresión: antes se devolvía el recurso de la otra ruta y la
    operación real nunca se ejecutaba, sin que nadie se enterara."""
    asignacion = AsignacionTallerService(db).crear(
        empresa.id, _datos_asignacion(lote, taller), idempotency_key=CLAVE
    )

    with pytest.raises(ConflictError):
        IncidenciaService(db).crear(
            empresa.id,
            IncidenciaCreate(
                asignacion_id=asignacion.id,
                tipo=TipoIncidencia.PRODUCTO_DANADO,
                cantidad_afectada=5,
                descripcion="daño de prueba",
                fecha=date(2026, 2, 2),
            ),
            idempotency_key=CLAVE,
        )


def test_cada_clave_nueva_crea_su_recurso(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    servicio = AsignacionTallerService(db)
    datos = _datos_asignacion(lote, taller)

    primera = servicio.crear(empresa.id, datos, idempotency_key="clave-a")
    segunda = servicio.crear(empresa.id, datos, idempotency_key="clave-b")

    assert primera.id != segunda.id


def _datos_devolucion(cantidad: int) -> AsignacionTallerRegistrarDevolucion:
    return AsignacionTallerRegistrarDevolucion(
        cantidad_devuelta=cantidad,
        fecha_devolucion=datetime(2026, 2, 5, tzinfo=timezone.utc),
    )


def test_reusar_la_clave_de_la_asignacion_en_su_devolucion_se_rechaza(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Regresión: crear una asignación y registrar su devolución producen las
    dos un recurso de tipo "asignacion", así que el tipo no bastaba para
    distinguirlas y solo se comparaba el tipo. Con la misma clave, la
    devolución respondía 200 con la asignación intacta y no se guardaba
    nunca -- el peor error posible, porque nadie se entera."""
    servicio = AsignacionTallerService(db)
    asignacion = servicio.crear(
        empresa.id, _datos_asignacion(lote, taller), idempotency_key=CLAVE
    )

    with pytest.raises(ConflictError):
        servicio.registrar_devolucion(
            asignacion.id, empresa.id, _datos_devolucion(40), idempotency_key=CLAVE
        )

    guardada = db.get(AsignacionTaller, asignacion.id)
    assert not guardada.cantidad_devuelta
    assert db.execute(select(Devolucion)).scalars().all() == []


def test_reintentar_la_misma_devolucion_no_la_duplica(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """La otra cara: con su propia clave, reenviar la MISMA devolución (doble
    clic, retry de red) devuelve el resultado anterior sin volver a sumar."""
    servicio = AsignacionTallerService(db)
    asignacion = servicio.crear(empresa.id, _datos_asignacion(lote, taller))

    primera = servicio.registrar_devolucion(
        asignacion.id, empresa.id, _datos_devolucion(40), idempotency_key=CLAVE
    )
    segunda = servicio.registrar_devolucion(
        asignacion.id, empresa.id, _datos_devolucion(40), idempotency_key=CLAVE
    )

    assert primera.cantidad_devuelta == segunda.cantidad_devuelta == 40
    assert len(db.execute(select(Devolucion)).scalars().all()) == 1


def test_doble_clic_no_duplica_el_corte(db: Session, empresa: Empresa, lote: Lote):
    """Regresión: registrar era el único POST de creación sin protección, y en
    producción quedaron cuatro lotes idénticos de un usuario que clicaba
    creyendo que no funcionaba.

    Antes el vehículo de esta prueba era crear un lote suelto. Ese camino se
    cerró: un lote es una línea de un corte y nace con él. La regresión sigue
    viva en el corte, que además gasta un número del ciclo por cada intento --
    o sea que un doble clic sin protección no solo duplica, también desordena
    la numeración de la planta.
    """
    servicio = CorteService(db)
    datos = CorteCreate(
        fecha=date(2026, 2, 1),
        lineas=[LineaCorteCreate(tipo_producto_id=lote.tipo_producto_id, cantidad=250)],
    )

    primero = servicio.crear(empresa.id, datos, idempotency_key=CLAVE)
    segundo = servicio.crear(empresa.id, datos, idempotency_key=CLAVE)

    assert primero.id == segundo.id
    # El del fixture más UNA línea: la segunda llamada no creó nada.
    assert len(db.execute(select(Lote)).scalars().all()) == 2
    db.refresh(empresa)
    assert empresa.corte_ultimo_numero == 1
