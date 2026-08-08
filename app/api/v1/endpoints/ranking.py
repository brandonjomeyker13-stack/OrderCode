# app/api/v1/endpoints/ranking.py
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.ranking import RankingTalleres
from app.services.ranking_service import RankingService

# Solo administradores. El ranking no es un tablero de producción más: junta
# en una tabla cuánto se le paga a cada taller, que es información de
# proveedores y suele ser reservada. Un operario que captura devoluciones no
# necesita saber que un taller cobra más que otro -- y enterarse suele
# terminar en una conversación incómoda para el dueño de la empresa.
#
# El precio por unidad sigue visible en el catálogo de productos y en las
# asignaciones: ahí es un parámetro de producción, no una nómina de
# proveedores. Si algún cliente pide taparlo también, se hace.
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
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Comparativa de talleres en un periodo: cuánto entregó cada uno, cuánto
    se dañó, qué tan rápido y qué le queda pendiente. Solo administradores.

    El periodo es libre porque cada empresa cierra distinto -- quincenal,
    mensual, o por lote terminado. Ambas fechas son inclusivas: pedir del 1 al
    15 incluye lo entregado el día 15.
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
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """El mismo ranking, descargable en Excel. Solo administradores.

    Existe porque hay gente que necesita estos números y no tiene cuenta en
    la app: el contador, un socio, el archivo del mes. Las cuentas ya vienen
    hechas del backend -- el Excel no es una calculadora, es el papel donde
    se imprime lo que la app calculó.
    """
    contenido, nombre = RankingService(db).exportar_excel(empresa_id, desde=desde, hasta=hasta)
    return Response(
        content=contenido,
        media_type=_MIME_EXCEL,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
