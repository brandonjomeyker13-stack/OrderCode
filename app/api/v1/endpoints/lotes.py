# app/api/v1/endpoints/lotes.py
from datetime import date

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.deps import puede_ver_cantidades, requiere_corte, require_admin
from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.lote import LoteConDisponibilidad, LoteOut, LoteUpdate
from app.services.lote_service import LoteService

router = APIRouter(prefix="/lotes", tags=["lotes"])

# Aquí NO hay POST. Un lote es una línea de un corte y nace con él
# (POST /cortes): crearlo suelto lo dejaba sin corte, sin color y sin
# proporciones, y con dos caminos para lo mismo el incompleto gana siempre,
# porque es el más corto. Lo que queda son las correcciones del admin y las
# lecturas, que son de todos.


@router.get("/{lote_id}", response_model=LoteConDisponibilidad)
def obtener_lote(
    lote_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    return LoteService(db).obtener_con_disponibilidad(lote_id, empresa_id)


@router.patch("/{lote_id}", response_model=LoteConDisponibilidad)
def actualizar_lote(
    lote_id: int,
    data: LoteUpdate,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return LoteService(db).actualizar(lote_id, empresa_id, data)


@router.delete("/{lote_id}", status_code=204)
def eliminar_lote(
    lote_id: int,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    LoteService(db).eliminar(lote_id, empresa_id)


@router.post("/{lote_id}/cerrar-cliente", response_model=LoteOut)
def cerrar_hacia_cliente(
    lote_id: int,
    fecha_entrega: date,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return LoteService(db).cerrar_hacia_cliente(lote_id, empresa_id, fecha_entrega)
from app.api.v1.deps import get_empresa_id, get_pagination
from app.schemas.common import PaginationParams

@router.get("", response_model=list[LoteConDisponibilidad])
def listar_lotes(
    response: Response,
    pagination: PaginationParams = Depends(get_pagination),
    empresa_id: int = Depends(get_empresa_id),
    _puesto: Usuario = Depends(puede_ver_cantidades),
    db: Session = Depends(get_db),
):
    service = LoteService(db)
    response.headers["X-Total-Count"] = str(service.contar(empresa_id))
    return service.listar(empresa_id, pagination.offset, pagination.page_size)