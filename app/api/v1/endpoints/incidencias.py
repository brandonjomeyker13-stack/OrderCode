# app/api/v1/endpoints/incidencias.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.schemas.common import PaginationParams
from app.schemas.incidencia import IncidenciaCreate, IncidenciaOut
from app.services.incidencia_service import IncidenciaService

router = APIRouter(prefix="/incidencias", tags=["incidencias"])


@router.post("", response_model=IncidenciaOut, status_code=201)
def crear_incidencia(
    data: IncidenciaCreate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return IncidenciaService(db).crear(empresa_id, data)


@router.get("", response_model=list[IncidenciaOut])
def listar_incidencias(
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return IncidenciaService(db).listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{incidencia_id}", response_model=IncidenciaOut)
def obtener_incidencia(
    incidencia_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return IncidenciaService(db).obtener(incidencia_id, empresa_id)