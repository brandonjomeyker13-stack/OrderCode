# app/api/v1/endpoints/clientes.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteCreate, ClienteOut, ClienteUpdate
from app.schemas.common import PaginationParams
from app.services.cliente_service import ClienteService

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("", response_model=ClienteOut, status_code=201)
def crear_cliente(
    data: ClienteCreate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return ClienteService(db).crear(empresa_id, data)


@router.get("", response_model=list[ClienteOut])
def listar_clientes(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = ClienteService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{cliente_id}", response_model=ClienteOut)
def obtener_cliente(
    cliente_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return ClienteService(db).obtener(cliente_id, empresa_id)


@router.patch("/{cliente_id}", response_model=ClienteOut)
def actualizar_cliente(
    cliente_id: int,
    data: ClienteUpdate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return ClienteService(db).actualizar(cliente_id, empresa_id, data)


@router.delete("/{cliente_id}", status_code=204)
def desactivar_cliente(
    cliente_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Solo admin, igual que dar de baja un taller -- registrar y corregir
    clientes es trabajo diario de cualquier usuario, pero darlos de baja no."""
    ClienteService(db).desactivar(cliente_id, empresa_id)