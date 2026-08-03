# app/api/v1/endpoints/lotes.py
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.api.v1.deps import get_empresa_id
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.lote import LoteCreate, LoteOut
from app.services.lote_service import LoteService

router = APIRouter(prefix="/lotes", tags=["lotes"])


@router.post("", response_model=LoteOut, status_code=201)
def crear_lote(
    data: LoteCreate,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return LoteService(db).crear(empresa_id, data)


@router.get("/{lote_id}", response_model=LoteOut)
def obtener_lote(
    lote_id: int,
    empresa_id: int = Depends(get_empresa_id),
    db: Session = Depends(get_db),
):
    return LoteService(db).obtener(lote_id, empresa_id)


@router.post("/{lote_id}/cerrar-cliente", response_model=LoteOut)
def cerrar_hacia_cliente(
    lote_id: int,
    fecha_entrega: date,
    empresa_id: int = Depends(get_empresa_id),
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return LoteService(db).cerrar_hacia_cliente(lote_id, empresa_id, fecha_entrega)