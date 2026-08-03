# app/api/v1/endpoints/empresas.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.empresa import EmpresaConEstadisticas, EmpresaUpdate
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