# app/api/v1/deps.py
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_usuario
from app.db.session import get_db
from app.models.usuario import Usuario
from app.schemas.common import PaginationParams


def get_empresa_id(usuario: Usuario = Depends(get_current_usuario)) -> int:
    """
    Punto único de extracción del tenant actual. Todo endpoint que toque
    datos de negocio depende de esto -- nunca del empresa_id que venga
    en el body/query de la request (eso permitiría a un usuario pedir
    datos de otra empresa con solo cambiar un número).
    """
    return usuario.empresa_id


def get_pagination(page: int = 1, page_size: int = 50) -> PaginationParams:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)  # tope duro para evitar abuso
    return PaginationParams(page=page, page_size=page_size)