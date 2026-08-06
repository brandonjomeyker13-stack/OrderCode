# app/api/v1/endpoints/empresas.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.empresa import (
    EmpresaConEstadisticas,
    EmpresaUpdate,
    SolicitarEliminacionCuenta,
)
from app.services.empresa_service import EmpresaService

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.get("/actual", response_model=EmpresaConEstadisticas)
def obtener_empresa_actual(
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return EmpresaService(db).obtener_con_estadisticas(empresa_id)


@router.patch("/actual", response_model=EmpresaConEstadisticas)
def actualizar_empresa_actual(
    data: EmpresaUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    EmpresaService(db).actualizar(empresa_id, data)
    return EmpresaService(db).obtener_con_estadisticas(empresa_id)


@router.post(
    "/actual/eliminar",
    response_model=EmpresaConEstadisticas,
    responses={
        401: {"description": "Contraseña incorrecta"},
        422: {"description": "La eliminación ya estaba programada"},
    },
)
def solicitar_eliminacion_cuenta(
    data: SolicitarEliminacionCuenta,
    empresa_id: int = Depends(get_empresa_id),
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Programa el borrado de TODA la cuenta y sus datos (derecho de supresión).
    No borra nada de inmediato: queda una ventana de gracia en la que se puede
    cancelar. Revisa `eliminacion_solicitada_at` en la respuesta."""
    service = EmpresaService(db)
    service.solicitar_eliminacion(empresa_id, admin, data.password)
    return service.obtener_con_estadisticas(empresa_id)


@router.post(
    "/actual/cancelar-eliminacion",
    response_model=EmpresaConEstadisticas,
    responses={422: {"description": "No hay ninguna eliminación programada"}},
)
def cancelar_eliminacion_cuenta(
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Solo sirve dentro de la ventana de gracia -- después de la purga los
    datos ya no existen y no hay nada que recuperar."""
    service = EmpresaService(db)
    service.cancelar_eliminacion(empresa_id)
    return service.obtener_con_estadisticas(empresa_id)