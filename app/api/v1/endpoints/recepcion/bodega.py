# app/api/v1/endpoints/recepcion/bodega.py
"""
Las rutas de quien cuenta.

Ninguna de estas respuestas lleva una cantidad enviada. No es una regla que
haya que recordar: los schemas de `app/schemas/recepcion.py` que se declaran
aquí no tienen esos campos.
"""
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import Contexto, get_contexto, get_pagination
from app.core.deps import requiere_bodega
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.recepcion import (
    ConteoBodegaOut,
    ConteoCreate,
    ConteoUpdate,
    PendienteDeRecibirOut,
)
from app.services.recepcion.bodega import RecepcionBodegaService

router = APIRouter()


@router.get("/pendientes", response_model=list[PendienteDeRecibirOut])
def listar_pendientes(
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
):
    """Qué bultos siguen en un taller. Dice QUÉ puede llegar, nunca CUÁNTO."""
    return RecepcionBodegaService(db).listar_pendientes(
        contexto.empresa_id, pagination.offset, pagination.page_size
    )


@router.post("/conteos", response_model=ConteoBodegaOut, status_code=201)
def registrar_conteo(
    data: ConteoCreate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga pasa
        # la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    """Anota lo que llegó. No se compara con lo enviado y no puede fallar por
    no cuadrar: el descuadre lo resuelve corte al confirmar."""
    return RecepcionBodegaService(db).registrar(
        contexto.empresa_id, data, contexto.usuario.id, idempotency_key
    )


@router.get("/conteos", response_model=list[ConteoBodegaOut])
def listar_conteos(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
):
    """El cuaderno de bodega: lo que anotó, confirmado o no."""
    servicio = RecepcionBodegaService(db)
    response.headers["X-Total-Count"] = str(servicio.repo.count(contexto.empresa_id))
    return servicio.listar_conteos(
        contexto.empresa_id, pagination.offset, pagination.page_size
    )


@router.get("/conteos/{conteo_id}", response_model=ConteoBodegaOut)
def obtener_conteo(
    conteo_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
):
    return RecepcionBodegaService(db).obtener(conteo_id, contexto.empresa_id)


@router.patch("/conteos/{conteo_id}", response_model=ConteoBodegaOut)
def corregir_conteo(
    conteo_id: int,
    data: ConteoUpdate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
):
    """Volver a contar y arreglar el propio reporte, mientras corte no lo haya
    confirmado. Es la salida cuando las cifras no cuadran."""
    return RecepcionBodegaService(db).corregir(conteo_id, contexto.empresa_id, data)


@router.delete("/conteos/{conteo_id}", status_code=204)
def eliminar_conteo(
    conteo_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
):
    """Para el reporte que nunca debió existir (se anotó el bulto equivocado)."""
    RecepcionBodegaService(db).eliminar(conteo_id, contexto.empresa_id)
