# app/api/v1/endpoints/talleres.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.taller import TallerCreate, TallerOut, TallerUpdate
from app.services.taller_service import TallerService

router = APIRouter(prefix="/talleres", tags=["talleres"])


@router.post("", response_model=TallerOut, status_code=201)
def crear_taller(
    data: TallerCreate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return TallerService(db).crear(empresa_id, data)


@router.get("", response_model=list[TallerOut])
def listar_talleres(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = TallerService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{taller_id}", response_model=TallerOut)
def obtener_taller(
    taller_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return TallerService(db).obtener(taller_id, empresa_id)


@router.patch("/{taller_id}", response_model=TallerOut)
def actualizar_taller(
    taller_id: int,
    data: TallerUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return TallerService(db).actualizar(taller_id, empresa_id, data)
@router.delete("/{taller_id}", status_code=204)
def desactivar_taller(
    taller_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    TallerService(db).desactivar(taller_id, empresa_id)