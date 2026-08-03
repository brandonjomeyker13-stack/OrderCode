# app/repositories/cliente_repository.py
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.repositories.base import BaseRepository


class ClienteRepository(BaseRepository[Cliente]):
    def __init__(self, db: Session):
        super().__init__(Cliente, db)