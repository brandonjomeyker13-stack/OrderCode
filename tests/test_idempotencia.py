# tests/test_idempotencia.py
"""
Protección contra doble clic: mandar la misma operación dos veces con la
misma Idempotency-Key no debe duplicar nada.
"""
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models.asignacion_taller import AsignacionTaller
from app.models.empresa import Empresa
from app.models.enums import TipoIncidencia
from app.models.lote import Lote
from app.models.taller import Taller
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService

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
