# app/api/v1/endpoints/alertas.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.schemas.alerta import ResumenAlertas
from app.services.alerta_service import AlertaService

router = APIRouter(prefix="/alertas", tags=["alertas"])


@router.get("", response_model=ResumenAlertas)
def obtener_alertas(
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    """Lotes que llevan demasiado tiempo en talleres sin cerrarse.

    El umbral de días se configura por empresa (`dias_alerta_atraso` en
    PATCH /empresas/actual). La lista viene ordenada del más atrasado al
    menos, que es el orden en que conviene atenderlos."""
    return AlertaService(db).resumen(empresa_id)
