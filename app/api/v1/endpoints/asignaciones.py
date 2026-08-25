# app/api/v1/endpoints/asignaciones.py
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.enums import EstadoAsignacion
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
    AsignacionTallerUpdate,
)
from app.schemas.common import PaginationParams
from app.schemas.filtros import FiltrosAsignacion
from app.services.asignacion_taller_service import AsignacionTallerService

router = APIRouter(prefix="/asignaciones", tags=["asignaciones"])


@router.post("", response_model=AsignacionTallerOut, status_code=201)
def crear_asignacion(
    data: AsignacionTallerCreate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga
        # pasa la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    return AsignacionTallerService(db).crear(empresa_id, data, idempotency_key)


@router.get("/{asignacion_id}", response_model=AsignacionTallerOut)
def obtener_asignacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).obtener_con_merma(asignacion_id, empresa_id)


@router.patch("/{asignacion_id}", response_model=AsignacionTallerOut)
def actualizar_asignacion(
    asignacion_id: int,
    data: AsignacionTallerUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).actualizar(asignacion_id, empresa_id, data)


@router.delete("/{asignacion_id}", status_code=204)
def eliminar_asignacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    AsignacionTallerService(db).eliminar(asignacion_id, empresa_id)


@router.post("/{asignacion_id}/reenviar-notificacion", response_model=AsignacionTallerOut)
def reenviar_notificacion(
    asignacion_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reintenta manualmente el envío de la ficha técnica por WhatsApp --
    revisa `notificacion_whatsapp_enviada` en la respuesta para confirmar
    si esta vez sí funcionó."""
    return AsignacionTallerService(db).reenviar_notificacion(asignacion_id, empresa_id)


@router.get("/por-lote/{lote_id}", response_model=list[AsignacionTallerOut])
def listar_por_lote(
    lote_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return AsignacionTallerService(db).listar_por_lote(lote_id, empresa_id)


@router.post("/{asignacion_id}/devolucion", response_model=AsignacionTallerOut)
def registrar_devolucion(
    asignacion_id: int,
    data: AsignacionTallerRegistrarDevolucion,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga
        # pasa la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    return AsignacionTallerService(db).registrar_devolucion(asignacion_id, empresa_id, data, idempotency_key)


@router.get("", response_model=list[AsignacionTallerOut])
def listar_asignaciones(
    response: Response,
    taller_id: int | None = Query(default=None, description="Solo las de este taller"),
    lote_id: int | None = Query(default=None, description="Solo las de este lote"),
    estado: EstadoAsignacion | None = Query(default=None, description="Filtra por estado"),
    desde: date | None = Query(
        default=None, description="fecha_asignacion >= desde (inclusive)"
    ),
    hasta: date | None = Query(
        default=None, description="fecha_asignacion <= hasta (inclusive)"
    ),
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    """Todos los filtros son opcionales y se aplican en la base de datos.
    X-Total-Count refleja el total YA filtrado, no el total de la empresa."""
    filtros = FiltrosAsignacion(
        taller_id=taller_id, lote_id=lote_id, estado=estado, desde=desde, hasta=hasta
    )
    service = AsignacionTallerService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id, filtros))
    return service.listar(empresa_id, pagination.offset, pagination.page_size, filtros)