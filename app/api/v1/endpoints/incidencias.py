# app/api/v1/endpoints/incidencias.py
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id, get_pagination
from app.core.deps import requiere_bodega, requiere_operacion, require_admin
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import AsignacionTallerOut
from app.schemas.common import PaginationParams
from app.schemas.incidencia import IncidenciaCreate, IncidenciaOut, IncidenciaUpdate
from app.services.incidencia_service import IncidenciaService

router = APIRouter(prefix="/incidencias", tags=["incidencias"])


@router.post("", response_model=IncidenciaOut, status_code=201)
def crear_incidencia(
    data: IncidenciaCreate,
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(requiere_bodega),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        # La columna es String(255): sin este tope, una clave más larga
        # pasa la validación y revienta como 500 al escribir en la base.
        max_length=255,
    ),
):
    return IncidenciaService(db).crear(empresa_id, data, idempotency_key)


@router.get("", response_model=list[IncidenciaOut])
def listar_incidencias(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(requiere_operacion),
    db: Session = Depends(get_db),
):
    service = IncidenciaService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)


@router.get("/{incidencia_id}", response_model=IncidenciaOut)
def obtener_incidencia(
    incidencia_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(requiere_operacion),
    db: Session = Depends(get_db),
):
    return IncidenciaService(db).obtener(incidencia_id, empresa_id)


@router.patch("/{incidencia_id}", response_model=IncidenciaOut)
def actualizar_incidencia(
    incidencia_id: int,
    data: IncidenciaUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Corrige una merma mal capturada (cantidad, tipo, descripción o fecha).
    Solo admin: cambiar la merma cambia lo que se le paga al taller."""
    return IncidenciaService(db).actualizar(incidencia_id, empresa_id, data)


@router.delete("/{incidencia_id}", status_code=204)
def eliminar_incidencia(
    incidencia_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Descarta una merma que se registró por error. Las unidades vuelven a
    quedar pendientes en el taller."""
    IncidenciaService(db).eliminar(incidencia_id, empresa_id)


@router.post("/{incidencia_id}/convertir-en-devolucion", response_model=AsignacionTallerOut)
def convertir_en_devolucion(
    incidencia_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """No era merma: el taller sí entregó esas unidades. Borra la incidencia y
    registra la devolución equivalente. Devuelve la asignación actualizada."""
    return IncidenciaService(db).convertir_en_devolucion(incidencia_id, empresa_id)