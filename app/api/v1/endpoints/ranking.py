# app/api/v1/endpoints/ranking.py
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.core.deps import requiere_corte
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.ranking import RankingTalleres
from app.services.ranking_service import RankingService

# Admin + corte. Corte es quien paga a los talleres y necesita ver, por
# periodo, cuánto entregó cada uno (unidades, merma, tiempos, pendiente).
# Bodega y ventas quedan fuera: no es su turno ni su decisión de pago.
#
# Antes era solo-admin porque la tabla también mostraba tarifas. Ya no hay
# plata en el sistema; lo que queda son cantidades de producción.
router = APIRouter(prefix="/ranking", tags=["ranking"])


@router.get("/talleres", response_model=RankingTalleres)
def ranking_de_talleres(
    desde: date | None = Query(
        default=None, description="Primer día del corte (inclusive). Por defecto, la quincena en curso."
    ),
    hasta: date | None = Query(
        default=None, description="Último día del corte (inclusive). Por defecto, hoy."
    ),
    empresa_id: int = Depends(get_empresa_id),
    _usuario: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """Comparativa de talleres en un periodo: cuánto entregó cada uno, cuánto
    se dañó, qué tan rápido y qué le queda pendiente. Admin y corte.

    El periodo es libre porque cada empresa cierra distinto -- quincena de
    sábado a sábado, mes, o un rango a mano si hay eventualidad. Ambas fechas
    son inclusivas: pedir del 1 al 15 incluye lo entregado el día 15.
    """
    return RankingService(db).talleres(empresa_id, desde=desde, hasta=hasta)


# El tipo MIME oficial de los .xlsx. Mandar otro (o application/octet-stream)
# hace que algunos navegadores y clientes de correo no ofrezcan abrirlo con
# Excel directamente.
_MIME_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/talleres.xlsx", response_class=Response)
def descargar_ranking_de_talleres(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    empresa_id: int = Depends(get_empresa_id),
    _usuario: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """El mismo ranking, descargable en Excel. Admin y corte.

    Existe porque hay gente que necesita estos números fuera de la app: el
    archivo del mes, un socio, o el propio corte al liquidar talleres. Las
    cuentas ya vienen hechas del backend -- el Excel no es una calculadora,
    es el papel donde se imprime lo que la app calculó.
    """
    contenido, nombre = RankingService(db).exportar_excel(empresa_id, desde=desde, hasta=hasta)
    return Response(
        content=contenido,
        media_type=_MIME_EXCEL,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
