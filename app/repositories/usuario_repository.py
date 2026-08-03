# app/repositories/usuario_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.usuario import Usuario
from app.repositories.base import BaseRepository


class UsuarioRepository(BaseRepository[Usuario]):
    def __init__(self, db: Session):
        super().__init__(Usuario, db)

    def get_by_email(self, email: str) -> Usuario | None:
        """
        Sin filtro de empresa_id a propósito: el login ocurre ANTES de saber
        a qué empresa pertenece la sesión -- el email es único globalmente
        (constraint en el modelo), así que esta es la única excepción
        legítima a la regla de oro. Se usa solo en el flujo de autenticación.
        """
        stmt = select(Usuario).where(Usuario.email == email)
        return self.db.execute(stmt).scalar_one_or_none()