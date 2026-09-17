# app/api/v1/endpoints/cortes.py
"""
El tendido y el catálogo de colores.

Registrar un corte es de CORTE. Leerlo lleva cantidades, así que lo ven los
tres que pueden verlas. El catálogo de colores lo lee todo el mundo: bodega
necesita el color para saber cuál de dos bultos del mismo producto tiene
delante, y un nombre de color no es una cantidad.
"""
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import Contexto, get_contexto, get_pagination
from app.core.deps import puede_ver_cantidades, require_admin, requiere_corte
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.corte import (
    ColorCreate,
    ColorOut,
    ColorUpdate,
    CorteCreate,
    CorteOut,
    CorteUpdate,
)
from app.services.color_service import ColorService
from app.services.corte_service import CorteService

router = APIRouter(tags=["cortes"])


# --- Colores ---


@router.get("/colores", response_model=list[ColorOut])
def listar_colores(
    incluir_inactivos: bool = False,
    contexto: Contexto = Depends(get_contexto),
    db: Session = Depends(get_db),
):
    """Sin guardia de puesto: es un catálogo, como los tipos de producto, y
    bodega lo necesita para distinguir dos bultos del mismo producto."""
    return ColorService(db).listar(contexto.empresa_id, incluir_inactivos)


@router.post("/colores", response_model=ColorOut, status_code=201)
def crear_color(
    data: ColorCreate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    return ColorService(db).crear(contexto.empresa_id, data)


@router.patch("/colores/{color_id}", response_model=ColorOut)
def actualizar_color(
    color_id: int,
    data: ColorUpdate,
    contexto: Contexto = Depends(get_contexto),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return ColorService(db).actualizar(color_id, contexto.empresa_id, data)


@router.delete("/colores/{color_id}", status_code=204)
def eliminar_color(
    color_id: int,
    contexto: Contexto = Depends(get_contexto),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Si el color ya se usó en un corte, se desactiva en vez de borrarse:
    borrarlo dejaría esa línea sin color y eso es perder historia."""
    ColorService(db).eliminar(color_id, contexto.empresa_id)


# --- Cortes ---


@router.post("/cortes", response_model=CorteOut, status_code=201)
def crear_corte(
    data: CorteCreate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga pasa
        # la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    """El tendido entero de una vez: cabecera y todas sus líneas.

    El número del ciclo lo pone el sistema, nunca el cliente. Y si el desglose
    no suma el total declarado, se guarda igual: la respuesta trae la
    diferencia para que se vea.
    """
    return CorteService(db).crear(contexto.empresa_id, data, idempotency_key)


@router.get("/cortes", response_model=list[CorteOut])
def listar_cortes(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    servicio = CorteService(db)
    response.headers["X-Total-Count"] = str(servicio.repo.count(contexto.empresa_id))
    return servicio.listar(contexto.empresa_id, pagination.offset, pagination.page_size)


@router.get("/cortes/{corte_id}", response_model=CorteOut)
def obtener_corte(
    corte_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    return CorteService(db).obtener(corte_id, contexto.empresa_id)


@router.patch("/cortes/{corte_id}", response_model=CorteOut)
def actualizar_corte(
    corte_id: int,
    data: CorteUpdate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_corte),
    db: Session = Depends(get_db),
):
    """Corrige un error de captura. Se puede rearmar el tendido mientras
    ninguna línea haya salido a taller; si ya salió, el service lo rechaza."""
    return CorteService(db).actualizar(corte_id, contexto.empresa_id, data)
