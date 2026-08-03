# app/services/taller_service.py
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.taller import Taller
from app.repositories.taller_repository import TallerRepository
from app.schemas.taller import TallerCreate, TallerUpdate


class TallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TallerRepository(db)

    def crear(self, empresa_id: int, data: TallerCreate) -> Taller:
        taller = Taller(empresa_id=empresa_id, **data.model_dump())
        try:
            taller = self.repo.create(taller)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError("Ya existe un taller registrado con ese número")
        self.db.refresh(taller)
        return taller

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[Taller]:
        return self.repo.list(empresa_id, offset, limit)

    def obtener(self, id: int, empresa_id: int) -> Taller:
        taller = self.repo.get_by_id(id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")
        return taller

    def actualizar(self, id: int, empresa_id: int, data: TallerUpdate) -> Taller:
        taller = self.obtener(id, empresa_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(taller, field, value)
        self.db.commit()
        self.db.refresh(taller)
        return taller