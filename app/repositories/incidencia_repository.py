# app/repositories/incidencia_repository.py
from sqlalchemy.orm import Session

from app.models.incidencia import Incidencia
from app.repositories.base import BaseRepository


class IncidenciaRepository(BaseRepository[Incidencia]):
    def __init__(self, db: Session):
        super().__init__(Incidencia, db)