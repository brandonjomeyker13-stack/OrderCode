# app/api/v1/endpoints/usuarios.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_usuario, require_admin
from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.usuario import CambioPassword, UsuarioCreate, UsuarioOut, UsuarioUpdate
from app.services.usuario_service import UsuarioService

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("", response_model=UsuarioOut, status_code=201)
def crear_usuario(
    data: UsuarioCreate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return UsuarioService(db).crear(empresa_id, data)


@router.get("", response_model=list[UsuarioOut])
def listar_usuarios(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    service = UsuarioService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{usuario_id}", response_model=UsuarioOut)
def obtener_usuario(
    usuario_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return UsuarioService(db).obtener(usuario_id, empresa_id)


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def actualizar_usuario(
    usuario_id: int,
    data: UsuarioUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return UsuarioService(db).actualizar(usuario_id, empresa_id, data)


@router.post("/{usuario_id}/cambiar-password", status_code=204)
def cambiar_password(
    usuario_id: int,
    data: CambioPassword,
    usuario_actual: Usuario = Depends(get_current_usuario),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    # Un usuario solo puede cambiar SU propia contraseña por esta ruta
    # (no la de otro, ni siquiera si es admin -- eso sería otra feature
    # explícita de "resetear contraseña", no esta).
    if usuario_actual.id != usuario_id:
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("Solo puedes cambiar tu propia contraseña")
    UsuarioService(db).cambiar_password(usuario_id, empresa_id, data)
    
@router.delete("/{usuario_id}", status_code=204)
def desactivar_usuario(
    usuario_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    UsuarioService(db).desactivar(usuario_id, empresa_id)