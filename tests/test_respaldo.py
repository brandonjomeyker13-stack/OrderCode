# tests/test_respaldo.py
"""
Respaldo y restauración. Lo que de verdad importa acá es el viaje de ida y
vuelta: un archivo que no se puede restaurar no es un respaldo, es un archivo.
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.respaldo import exportar, importar
from app.models.asignacion_taller import AsignacionTaller
from app.models.empresa import Empresa
from app.models.lote import Lote
from app.models.taller import Taller
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.services.asignacion_taller_service import AsignacionTallerService


@pytest.fixture
def con_datos(db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller):
    """Una empresa con operación real: asignación y devolución parcial."""
    lote.tipo_producto.precio_unitario = Decimal("1500.50")
    db.commit()
    asignacion = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=200,
            fecha_asignacion=date(2026, 2, 1),
        ),
    )
    AsignacionTallerService(db).registrar_devolucion(
        asignacion.id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=80, fecha_devolucion=datetime(2026, 2, 5, tzinfo=timezone.utc)
        ),
    )
    return asignacion


def _contar(db: Session, modelo) -> int:
    return db.execute(select(func.count()).select_from(modelo)).scalar_one()


def test_el_respaldo_incluye_todas_las_tablas(db: Session, con_datos, tmp_path: Path):
    archivo = tmp_path / "respaldo.json"

    exportar(db, archivo)

    contenido = json.loads(archivo.read_text(encoding="utf-8"))
    assert contenido["formato_version"] == 1
    # Si algún día se agrega una tabla y no queda en el respaldo, esos datos
    # se perderían en silencio al restaurar.
    for tabla in ("empresas", "usuarios", "talleres", "lotes", "asignaciones_taller"):
        assert tabla in contenido["tablas"], f"falta {tabla} en el respaldo"


def test_ida_y_vuelta_conserva_los_datos(db: Session, con_datos, tmp_path: Path):
    """La prueba que de verdad importa: exportar, borrar todo, restaurar, y
    que quede exactamente igual."""
    archivo = tmp_path / "respaldo.json"
    exportar(db, archivo)

    antes = {
        modelo.__name__: _contar(db, modelo)
        for modelo in (Empresa, Usuario, Taller, Lote, AsignacionTaller)
    }
    asignacion_original = db.execute(select(AsignacionTaller)).scalars().one()
    datos_originales = (
        asignacion_original.cantidad_asignada,
        asignacion_original.cantidad_devuelta,
        asignacion_original.estado,
    )

    importar(db, archivo)

    for nombre, cantidad in antes.items():
        modelo = {
            "Empresa": Empresa, "Usuario": Usuario, "Taller": Taller,
            "Lote": Lote, "AsignacionTaller": AsignacionTaller,
        }[nombre]
        assert _contar(db, modelo) == cantidad, f"se perdieron filas de {nombre}"

    restaurada = db.execute(select(AsignacionTaller)).scalars().one()
    assert (
        restaurada.cantidad_asignada,
        restaurada.cantidad_devuelta,
        restaurada.estado,
    ) == datos_originales


def test_los_precios_sobreviven_el_viaje(db: Session, con_datos, tmp_path: Path):
    """La plata viaja como texto en el JSON y tiene que volver como número
    exacto. Si vuelve mal, el respaldo se restaura sin errores y los montos a
    pagar quedan corridos -- la peor forma de fallar, porque nadie lo nota."""
    archivo = tmp_path / "respaldo.json"
    exportar(db, archivo)

    importar(db, archivo)

    restaurada = db.execute(select(AsignacionTaller)).scalars().one()
    assert restaurada.precio_unitario == Decimal("1500.50")


def test_restaurar_reemplaza_lo_que_hubiera(db: Session, con_datos, tmp_path: Path):
    """Restaurar deja la base como el archivo, no mezclada con lo que había:
    si no, recuperar un respaldo dejaría datos fantasma."""
    archivo = tmp_path / "respaldo.json"
    exportar(db, archivo)

    db.add(Empresa(nombre="Empresa Que No Estaba", activo=True))
    db.commit()
    assert _contar(db, Empresa) == 2

    importar(db, archivo)

    assert _contar(db, Empresa) == 1
    assert db.execute(select(Empresa)).scalars().one().nombre == "Empresa de Prueba"


def test_se_puede_seguir_creando_despues_de_restaurar(
    db: Session, con_datos, tmp_path: Path, empresa: Empresa
):
    """Tras insertar filas con id explícito, el contador de la base queda atrás
    y el siguiente INSERT chocaría con un id ya usado."""
    archivo = tmp_path / "respaldo.json"
    exportar(db, archivo)
    importar(db, archivo)

    nuevo = Taller(
        empresa_id=empresa.id, nombre="Taller Nuevo", numero_taller="T-999", telefono="3001234567"
    )
    db.add(nuevo)
    db.commit()

    assert nuevo.id is not None


def test_se_rechaza_un_formato_desconocido(db: Session, tmp_path: Path):
    archivo = tmp_path / "raro.json"
    archivo.write_text(json.dumps({"formato_version": 99, "tablas": {}}), encoding="utf-8")

    with pytest.raises(ValueError):
        importar(db, archivo)
