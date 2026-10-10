# app/api/v1/endpoints/recepcion/corte.py
"""
Las rutas de quien confirma.

Estas SÍ llevan las dos cifras, una al lado de la otra, porque ese es el
momento del producto: ver lo que salió contra lo que volvió. Por eso están en
un archivo aparte del de bodega y con otra guardia.
"""
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import Contexto, get_contexto, get_pagination
from app.core.deps import requiere_corte
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.recepcion import ConteoPorConfirmarOut
from app.services.recepcion.corte import ConfirmacionCorteService

router = APIRouter()


@router.get("/recibido", response_model=list[ConteoPorConfirmarOut])
def listar_recibido(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """Lo que bodega ya contó y quedó para ventas. Solo informativo."""
    servicio = ConfirmacionCorteService(db)
    response.headers["X-Total-Count"] = str(servicio.contar_recibido(contexto.empresa_id))
    return servicio.listar_recibido(contexto.empresa_id, pagination.offset, pagination.page_size)


@router.get("/por-confirmar", response_model=list[ConteoPorConfirmarOut])
def listar_por_confirmar(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """Lo que bodega ya contó y nadie ha dado por bueno.

    X-Total-Count es el número que el front pinta como aviso: mientras sea
    mayor que cero hay saldo de talleres esperando una revisión.
    """
    servicio = ConfirmacionCorteService(db)
    response.headers["X-Total-Count"] = str(servicio.contar_por_confirmar(contexto.empresa_id))
    return servicio.listar_por_confirmar(
        contexto.empresa_id, pagination.offset, pagination.page_size
    )


@router.get("/conteos/{conteo_id}/comparacion", response_model=ConteoPorConfirmarOut)
def ver_comparacion(
    conteo_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """Un conteo con lo enviado al lado, para poder hablarlo con bodega."""
    return ConfirmacionCorteService(db).obtener(conteo_id, contexto.empresa_id)


@router.post("/conteos/{conteo_id}/confirmar", response_model=ConteoPorConfirmarOut)
def confirmar_conteo(
    conteo_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        max_length=255,
    ),
):
    """Dar por bueno el conteo. Aquí se descuenta el saldo del taller y se
    mueven los estados: hasta este momento el reporte no había movido nada."""
    return ConfirmacionCorteService(db).confirmar(
        conteo_id, contexto.empresa_id, contexto.usuario.id, idempotency_key
    )
