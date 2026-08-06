# app/repositories/taller_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.taller import Taller
from app.repositories.base import BaseRepository


class TallerRepository(BaseRepository[Taller]):
    def __init__(self, db: Session):
        super().__init__(Taller, db)

    def numeros_asignados(self, empresa_id: int) -> list[str]:
        """Todos los números ya usados por esta empresa, incluidos los de
        talleres inactivos: un número dado de baja no se reutiliza, porque
        volvería ambiguo el histórico de asignaciones viejas.

        Se traen a memoria en vez de calcular el máximo en SQL porque la
        columna es texto (puede haber formatos heredados tipo "T-01") y un
        CAST a entero sería específico del motor. Una empresa tiene decenas
        de talleres, no millones."""
        stmt = select(Taller.numero_taller).where(Taller.empresa_id == empresa_id)
        return list(self.db.execute(stmt).scalars().all())
