# app/repositories/taller_repository.py
from sqlalchemy.orm import Session

from app.models.taller import Taller
from app.repositories.base import BaseRepository


class TallerRepository(BaseRepository[Taller]):
    def __init__(self, db: Session):
        super().__init__(Taller, db)