# app/api/v1/endpoints/notificaciones.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_empresa_id
from app.core.deps import get_current_usuario
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.centro_notificaciones import CentroNotificaciones
from app.services.centro_notificaciones_service import CentroNotificacionesService

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("", response_model=CentroNotificaciones)
def listar_notificaciones(
    empresa_id: int = Depends(get_empresa_id),
    usuario: Usuario = Depends(get_current_usuario),
    db: Session = Depends(get_db),
):
    """Avisos para la campanita: lotes atrasados, fichas técnicas que no se
    pudieron enviar, e incidencias recientes.

    Se calculan al momento, así que siempre reflejan el estado real: cuando un
    lote atrasado se entrega, su aviso desaparece solo. El campo `leida` es
    por usuario."""
    return CentroNotificacionesService(db).listar(empresa_id, usuario.id)


@router.post("/leer-todas", status_code=204)
def marcar_todas_leidas(
    empresa_id: int = Depends(get_empresa_id),
    usuario: Usuario = Depends(get_current_usuario),
    db: Session = Depends(get_db),
):
    """Marca como leídos los avisos que existen en este momento. Los que
    aparezcan después siguen sin leer."""
    CentroNotificacionesService(db).marcar_todas_leidas(empresa_id, usuario.id)


@router.post("/{aviso_id}/leer", status_code=204)
def marcar_leida(
    aviso_id: str,
    usuario: Usuario = Depends(get_current_usuario),
    db: Session = Depends(get_db),
):
    """`aviso_id` es el campo `id` del aviso (una clave como
    "lote_atrasado:asignacion:42"), no un número. Es idempotente."""
    CentroNotificacionesService(db).marcar_leida(usuario.id, aviso_id)
