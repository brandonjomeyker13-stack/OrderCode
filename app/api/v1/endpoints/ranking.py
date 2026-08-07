# app/api/v1/endpoints/ranking.py
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.schemas.ranking import RankingTalleres
from app.services.ranking_service import RankingService

router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("/talleres", response_model=RankingTalleres)
def ranking_de_talleres(
    desde: date | None = Query(
        default=None, description="Primer día del corte (inclusive). Por defecto, 30 días atrás."
    ),
    hasta: date | None = Query(
        default=None, description="Último día del corte (inclusive). Por defecto, hoy."
    ),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    """Comparativa de talleres en un periodo: cuánto entregó cada uno, cuánto
    se dañó, qué tan rápido y qué le queda pendiente.

    El periodo es libre porque cada empresa cierra distinto -- quincenal,
    mensual, o por lote terminado. Ambas fechas son inclusivas: pedir del 1 al
    15 incluye lo entregado el día 15.
    """
    return RankingService(db).talleres(empresa_id, desde=desde, hasta=hasta)
