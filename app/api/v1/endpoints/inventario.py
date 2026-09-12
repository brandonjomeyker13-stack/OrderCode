# app/api/v1/endpoints/inventario.py
"""
El final del recorrido: lo que ya está listo y sacarlo.

LEER lo puede hacer quien ve cantidades -- ventas, corte y el dueño --, porque
saber qué hay listo es información de producción. ESCRIBIR es solo de ventas:
quien despacha es quien registra la salida.
"""
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import Contexto, get_contexto, get_pagination
from app.core.deps import puede_ver_cantidades, requiere_ventas
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams
from app.schemas.inventario import (
    ResumenInventarioOut,
    VentaCreate,
    VentaOut,
    VentaUpdate,
)
from app.services.inventario_service import InventarioService

router = APIRouter(prefix="/inventario", tags=["inventario"])


@router.get("", response_model=ResumenInventarioOut)
def ver_inventario(
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    """Lo que volvió bien de los talleres, ya confirmado, menos lo vendido.

    Un conteo que bodega registró y corte todavía no confirmó NO aparece aquí:
    hasta que no se revise, esas prendas siguen contando como si estuvieran en
    el taller.
    """
    return InventarioService(db).resumen(
        contexto.empresa_id, pagination.offset, pagination.page_size
    )


@router.post("/ventas", response_model=VentaOut, status_code=201)
def registrar_venta(
    data: VentaCreate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_ventas),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga pasa
        # la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    return InventarioService(db).registrar(
        contexto.empresa_id, data, contexto.usuario.id, idempotency_key
    )


@router.get("/ventas", response_model=list[VentaOut])
def listar_ventas(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    servicio = InventarioService(db)
    response.headers["X-Total-Count"] = str(servicio.repo.count(contexto.empresa_id))
    return servicio.listar_ventas(contexto.empresa_id, pagination.offset, pagination.page_size)


@router.patch("/ventas/{venta_id}", response_model=VentaOut)
def corregir_venta(
    venta_id: int,
    data: VentaUpdate,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_ventas),
    db: Session = Depends(get_db),
):
    """Corrección de captura. Quien despacha corrige lo suyo: aquí no hay un
    segundo par de ojos que proteger -- el control de dos manos es el de la
    recepción, no el de la salida."""
    return InventarioService(db).actualizar(venta_id, contexto.empresa_id, data)


@router.delete("/ventas/{venta_id}", status_code=204)
def eliminar_venta(
    venta_id: int,
    contexto: Contexto = Depends(get_contexto),
    _puesto: Usuario = Depends(requiere_ventas),
    db: Session = Depends(get_db),
):
    """Las unidades vuelven al inventario solas: el disponible se calcula."""
    InventarioService(db).eliminar(venta_id, contexto.empresa_id)
