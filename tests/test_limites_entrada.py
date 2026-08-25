# tests/test_limites_entrada.py
"""
Topes de las cantidades que entran por la API.

Existen por una razón que los demás tests NO pueden ver: las columnas de
cantidad son INTEGER en PostgreSQL (máximo 2.147.483.647), pero la suite corre
sobre SQLite, que no tiene ese límite. Sin un tope en el schema, un número
mayor pasaba la validación, llegaba a la base y reventaba con un 500 en
producción -- mientras acá todo seguía en verde.

Por eso estos tests comprueban el SCHEMA y no el comportamiento de la base: es
la única capa donde el límite se puede verificar sin PostgreSQL delante.
"""
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.enums import TipoIncidencia
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
    AsignacionTallerUpdate,
)
from app.schemas.common import MAX_UNIDADES
from app.schemas.incidencia import IncidenciaCreate
from app.schemas.lote import LoteCreate, LoteUpdate

# El límite del INTEGER de PostgreSQL. Cualquier cosa por encima reventaba.
MAX_INTEGER_POSTGRES = 2_147_483_647


def test_el_tope_esta_por_debajo_del_limite_de_postgres():
    """Si alguien sube MAX_UNIDADES por encima de esto, vuelve el bug."""
    assert MAX_UNIDADES < MAX_INTEGER_POSTGRES


@pytest.mark.parametrize(
    "construir",
    [
        lambda n: LoteCreate(tipo_producto_id=1, cantidad_total=n, fecha_registro=date(2026, 1, 1)),
        lambda n: LoteUpdate(cantidad_total=n),
        lambda n: AsignacionTallerCreate(
            lote_id=1, taller_id=1, cantidad_asignada=n, fecha_asignacion=date(2026, 1, 1)
        ),
        lambda n: AsignacionTallerUpdate(cantidad_asignada=n),
        lambda n: AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=n, fecha_devolucion=datetime(2026, 1, 1, tzinfo=timezone.utc)
        ),
        lambda n: IncidenciaCreate(
            asignacion_id=1, tipo=TipoIncidencia.PRODUCTO_DANADO, cantidad_afectada=n,
            descripcion="x", fecha=date(2026, 1, 1),
        ),
    ],
    ids=["lote_crear", "lote_editar", "asignar", "asignar_editar", "devolver", "merma"],
)
def test_rechaza_cantidades_que_reventarian_postgres(construir):
    for absurdo in (MAX_UNIDADES + 1, MAX_INTEGER_POSTGRES + 1, 5_000_000_000):
        with pytest.raises(ValidationError):
            construir(absurdo)


@pytest.mark.parametrize(
    "construir",
    [
        lambda n: LoteCreate(tipo_producto_id=1, cantidad_total=n, fecha_registro=date(2026, 1, 1)),
        lambda n: AsignacionTallerCreate(
            lote_id=1, taller_id=1, cantidad_asignada=n, fecha_asignacion=date(2026, 1, 1)
        ),
    ],
    ids=["lote_crear", "asignar"],
)
def test_una_cantidad_grande_pero_razonable_si_pasa(construir):
    """El tope no puede estorbarle a un cliente real. El más grande produce
    ~100.000 unidades al mes."""
    assert construir(1_000_000) is not None
    assert construir(MAX_UNIDADES) is not None
