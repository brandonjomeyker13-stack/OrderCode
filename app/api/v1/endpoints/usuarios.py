# app/api/v1/endpoints/usuarios.py
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import get_current_usuario, require_admin
from app.api.v1.deps import get_empresa_id, get_pagination
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.usuario import (
    CambioPassword,
    ConfigurarPasswordInicial,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
)
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
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    service = UsuarioService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{usuario_id}", response_model=UsuarioOut)
def obtener_usuario(
    usuario_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
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


@router.post(
    "/me/configurar-password",
    status_code=204,
    responses={422: {"description": "La cuenta ya tiene una contraseña configurada"}},
)
def configurar_password_inicial(
    data: ConfigurarPasswordInicial,
    usuario_actual: Usuario = Depends(get_current_usuario),
    db: Session = Depends(get_db),
):
    """Solo para cuentas creadas por Google Sign-In (password_configurada=False
    en UsuarioOut) -- ponen su primera contraseña real sin necesitar una
    contraseña actual que no existe."""
    UsuarioService(db).configurar_password_inicial(
        usuario_actual.id, usuario_actual.empresa_id, data
    )


@router.delete(
    "/{usuario_id}",
    status_code=204,
    responses={422: {"description": "No se puede dar de baja al único administrador activo"}},
)
def desactivar_usuario(
    usuario_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Baja reversible: el usuario deja de entrar pero sus datos se conservan.
    Para borrar sus datos personales, ver /anonimizar."""
    UsuarioService(db).desactivar(usuario_id, empresa_id)


@router.post(
    "/{usuario_id}/anonimizar",
    status_code=204,
    responses={422: {"description": "No se puede dar de baja al único administrador activo"}},
)
def anonimizar_usuario(
    usuario_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Borra el nombre y el correo del usuario para atender una solicitud de
    supresión de datos personales. IRREVERSIBLE: no se pueden recuperar."""
    UsuarioService(db).anonimizar(usuario_id, empresa_id)