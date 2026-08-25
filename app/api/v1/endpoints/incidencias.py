# app/api/v1/endpoints/incidencias.py
from fastapi import APIRouter, Depends, Header, Response
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
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga
        # pasa la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    return IncidenciaService(db).crear(empresa_id, data, idempotency_key)


@router.get("", response_model=list[IncidenciaOut])
def listar_incidencias(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = IncidenciaService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{incidencia_id}", response_model=IncidenciaOut)
def obtener_incidencia(
    incidencia_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return IncidenciaService(db).obtener(incidencia_id, empresa_id)