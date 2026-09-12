# app/api/v1/endpoints/resumen.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import puede_ver_cantidades
from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.resumen import ResumenGeneral
from app.services.resumen_service import ResumenService

router = APIRouter(prefix="/resumen", tags=["resumen"])


@router.get("", response_model=ResumenGeneral)
def obtener_resumen(
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    """Cifras del tablero principal en una sola llamada. Todo se agrega en la
    base de datos: el front no debería tener que traerse los listados
    completos de lotes/asignaciones/incidencias solo para sumarlos."""
    return ResumenService(db).general(empresa_id)
