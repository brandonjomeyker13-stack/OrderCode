# app/api/v1/endpoints/tipos_producto.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.lote import LoteConDisponibilidad
from app.schemas.tipo_producto import TipoProductoCreate, TipoProductoOut, TipoProductoUpdate
from app.services.lote_service import LoteService
from app.services.tipo_producto_service import TipoProductoService

router = APIRouter(prefix="/tipos-producto", tags=["tipos-producto"])


@router.post("", response_model=TipoProductoOut, status_code=201)
def crear_tipo_producto(
    data: TipoProductoCreate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return TipoProductoService(db).crear(empresa_id, data)


@router.get("", response_model=list[TipoProductoOut])
def listar_tipos_producto(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = TipoProductoService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{tipo_producto_id}", response_model=TipoProductoOut)
def obtener_tipo_producto(
    tipo_producto_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return TipoProductoService(db).obtener(tipo_producto_id, empresa_id)


@router.patch("/{tipo_producto_id}", response_model=TipoProductoOut)
def actualizar_tipo_producto(
    tipo_producto_id: int,
    data: TipoProductoUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return TipoProductoService(db).actualizar(tipo_producto_id, empresa_id, data)


@router.post("/{tipo_producto_id}/regenerar-qr", response_model=TipoProductoOut)
def regenerar_qr(
    tipo_producto_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return TipoProductoService(db).regenerar_qr(tipo_producto_id, empresa_id)


@router.get("/qr/{token}", response_model=TipoProductoOut)
def escanear_qr(
    token: str,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    """Requiere sesión activa (ver nota pendiente en tipo_producto_service
    sobre si esto debe funcionar sin login)."""
    return TipoProductoService(db).obtener_por_qr_token(token, empresa_id)


@router.get("/qr/{token}/lotes-activos", response_model=list[LoteConDisponibilidad])
def lotes_activos_por_qr(
    token: str,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    """Vista principal al escanear el QR: lotes activos + disponibilidad."""
    tipo_producto = TipoProductoService(db).obtener_por_qr_token(token, empresa_id)
    return LoteService(db).listar_activos_por_tipo_producto(tipo_producto.id, empresa_id)
@router.delete("/{tipo_producto_id}", status_code=204)
def eliminar_tipo_producto(
    tipo_producto_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    TipoProductoService(db).eliminar(tipo_producto_id, empresa_id)