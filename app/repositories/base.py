# app/repositories/base.py
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Repository genérico con operaciones CRUD comunes.
    REGLA DE ORO: todo método que lea/escriba una fila exige `empresa_id`
    como parámetro obligatorio (no opcional, no con default). Esto es
    la capa de respaldo del backend independiente de RLS -- si RLS
    falla o se mal-configura, esta capa igual impide fuga entre tenants.
    """

    def __init__(self, model: type[ModelType], db: Session):
        self.model = model
        self.db = db

    def get_by_id(self, id: int, empresa_id: int) -> ModelType | None:
        stmt = select(self.model).where(
            self.model.id == id,
            self.model.empresa_id == empresa_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list(
        self,
        empresa_id: int,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ModelType]:
        stmt = (
            select(self.model)
            .where(self.model.empresa_id == empresa_id)
            .offset(offset)
            .limit(limit)
            .order_by(self.model.id.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def count(self, empresa_id: int) -> int:
        stmt = select(func.count()).select_from(self.model).where(
            self.model.empresa_id == empresa_id
        )
        return self.db.execute(stmt).scalar_one()

    def create(self, obj_in: ModelType) -> ModelType:
        self.db.add(obj_in)
        self.db.flush()  # obtiene el id sin cerrar la transacción todavía
        self.db.refresh(obj_in)
        return obj_in

    def delete(self, id: int, empresa_id: int) -> bool:
        obj = self.get_by_id(id, empresa_id)
        if obj is None:
            return False
        self.db.delete(obj)
        self.db.flush()
        return True