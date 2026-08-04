# app/api/v1/endpoints/asignaciones.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
)
from app.services.asignacion_taller_service import AsignacionTallerService
from app.api.v1.deps import get_empresa_id, get_pagination
from app.schemas.common import PaginationParams

router = APIRouter(prefix="/asignaciones", tags=["asignaciones"])


@router.post("", response_model=AsignacionTallerOut, status_code=201)
def crear_asignacion(
    data: AsignacionTallerCreate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).crear(empresa_id, data)


@router.get("/{asignacion_id}", response_model=AsignacionTallerOut)
def obtener_asignacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).obtener_con_merma(asignacion_id, empresa_id)


@router.get("/por-lote/{lote_id}", response_model=list[AsignacionTallerOut])
def listar_por_lote(
    lote_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).listar_por_lote(lote_id, empresa_id)


@router.post("/{asignacion_id}/devolucion", response_model=AsignacionTallerOut)
def registrar_devolucion(
    asignacion_id: int,
    data: AsignacionTallerRegistrarDevolucion,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).registrar_devolucion(asignacion_id, empresa_id, data)


@router.get("", response_model=list[AsignacionTallerOut])
def listar_asignaciones(
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).listar(empresa_id, pagination.offset, pagination.page_size)