# app/core/respaldo.py
"""
Respaldo y restauración de toda la base en un archivo JSON.

Por qué así y no con pg_dump: pg_dump exige tener instaladas las herramientas
cliente de PostgreSQL en la máquina que corre el respaldo, y el plan gratuito
de Supabase no hace copias automáticas. Esto solo necesita Python y la misma
conexión que ya usa la app, así que funciona desde cualquier lado.

No reemplaza a un respaldo administrado de verdad -- cuando el proyecto pueda
pagarlo, eso es lo correcto. Mientras tanto, esto es la diferencia entre poder
recuperar los datos de un cliente y perderlos para siempre.
"""
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401  -- registra todas las tablas en Base.metadata
from app.db.base import Base

# Orden de dependencias: las tablas se escriben en este orden al restaurar
# (padres antes que hijos) y se vacían en el orden inverso. Base.metadata
# .sorted_tables ya resuelve esto leyendo las llaves foráneas.
_TABLAS = Base.metadata.sorted_tables

FORMATO_VERSION = 1


def _serializar(valor: Any) -> Any:
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, bytes):
        return valor.decode("utf-8", errors="replace")
    return valor


def _deserializar_fila(tabla, fila: dict[str, Any]) -> dict[str, Any]:
    """Devuelve las fechas a objetos de Python. En el JSON viajan como texto
    ISO, pero la base las rechaza así -- sin esta conversión el respaldo se
    genera bien pero NO se puede restaurar, que es la peor forma de fallar."""
    convertida = {}
    for nombre, valor in fila.items():
        columna = tabla.columns.get(nombre)
        if valor is None or columna is None:
            convertida[nombre] = valor
            continue

        tipo = type(columna.type).__name__
        if tipo == "DateTime" and isinstance(valor, str):
            convertida[nombre] = datetime.fromisoformat(valor)
        elif tipo == "Date" and isinstance(valor, str):
            convertida[nombre] = date.fromisoformat(valor)
        else:
            convertida[nombre] = valor
    return convertida


def _revision_alembic(db: Session) -> str | None:
    """Deja anotado contra qué versión del esquema se tomó el respaldo: un
    volcado no sirve de nada si después no se sabe a qué estructura corresponde."""
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        return None


def exportar(db: Session, destino: Path) -> dict[str, int]:
    """Vuelca todas las tablas a un JSON. Devuelve cuántas filas salió cada una."""
    datos: dict[str, list[dict]] = {}
    conteos: dict[str, int] = {}

    for tabla in _TABLAS:
        filas = [
            {c.name: _serializar(fila[i]) for i, c in enumerate(tabla.columns)}
            for fila in db.execute(select(tabla)).all()
        ]
        datos[tabla.name] = filas
        conteos[tabla.name] = len(filas)

    contenido = {
        "formato_version": FORMATO_VERSION,
        "generado_en": datetime.now().astimezone().isoformat(),
        "revision_alembic": _revision_alembic(db),
        "tablas": datos,
    }

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return conteos


def importar(db: Session, origen: Path, *, vaciar_antes: bool = True) -> dict[str, int]:
    """
    Restaura un respaldo. DESTRUCTIVO: por defecto vacía las tablas antes de
    escribir, para que el resultado sea exactamente el del archivo y no una
    mezcla con lo que hubiera.

    No toca `alembic_version`: el esquema tiene que existir antes (correr
    `alembic upgrade head` primero).
    """
    contenido = json.loads(origen.read_text(encoding="utf-8"))
    if contenido.get("formato_version") != FORMATO_VERSION:
        raise ValueError(
            f"Formato de respaldo desconocido: {contenido.get('formato_version')!r}"
        )

    tablas = contenido["tablas"]
    conteos: dict[str, int] = {}

    if vaciar_antes:
        # Al revés que al insertar: primero los hijos, después los padres.
        for tabla in reversed(_TABLAS):
            db.execute(delete(tabla))

    for tabla in _TABLAS:
        filas = tablas.get(tabla.name, [])
        if filas:
            db.execute(insert(tabla), [_deserializar_fila(tabla, f) for f in filas])
        conteos[tabla.name] = len(filas)

    db.commit()
    _resincronizar_secuencias(db)
    return conteos


def _resincronizar_secuencias(db: Session) -> None:
    """Tras insertar filas con id explícito, el contador de PostgreSQL sigue
    donde estaba y el próximo INSERT chocaría con un id ya usado. SQLite no
    tiene este problema, por eso se ignora el error ahí."""
    for tabla in _TABLAS:
        if "id" not in tabla.columns:
            continue
        try:
            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence(:tabla, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + tabla.name + "), 1), true)"
                ),
                {"tabla": tabla.name},
            )
        except Exception:
            db.rollback()
            return
    db.commit()
