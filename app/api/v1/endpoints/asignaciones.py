# app/api/v1/endpoints/asignaciones.py
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
    AsignacionTallerUpdate,
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return AsignacionTallerService(db).crear(empresa_id, data, idempotency_key)


@router.get("/{asignacion_id}", response_model=AsignacionTallerOut)
def obtener_asignacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).obtener_con_merma(asignacion_id, empresa_id)


@router.patch("/{asignacion_id}", response_model=AsignacionTallerOut)
def actualizar_asignacion(
    asignacion_id: int,
    data: AsignacionTallerUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).actualizar(asignacion_id, empresa_id, data)


@router.delete("/{asignacion_id}", status_code=204)
def eliminar_asignacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    AsignacionTallerService(db).eliminar(asignacion_id, empresa_id)


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    return AsignacionTallerService(db).registrar_devolucion(asignacion_id, empresa_id, data, idempotency_key)


@router.get("", response_model=list[AsignacionTallerOut])
def listar_asignaciones(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = AsignacionTallerService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)