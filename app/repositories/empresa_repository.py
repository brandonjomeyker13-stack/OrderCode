# app/repositories/empresa_repository.py
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.taller import Taller
from app.models.usuario import Usuario


class EmpresaRepository:
    """
    Empresa es especial: no hereda de BaseRepository porque sus queries
    NO se filtran por empresa_id (una empresa se filtra por su propio id).
    Es la única tabla raíz del multi-tenant.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, id: int) -> Empresa | None:
        return self.db.get(Empresa, id)

    def create(self, empresa: Empresa) -> Empresa:
        self.db.add(empresa)
        self.db.flush()
        self.db.refresh(empresa)
        return empresa

    def contar_talleres(self, empresa_id: int) -> int:
        """Calculado en vivo -- no se guarda como columna (ver decisión previa)."""
        stmt = select(func.count()).select_from(Taller).where(
            Taller.empresa_id == empresa_id, Taller.activo.is_(True)
        )
        return self.db.execute(stmt).scalar_one()

    def contar_usuarios(self, empresa_id: int) -> int:
        stmt = select(func.count()).select_from(Usuario).where(
            Usuario.empresa_id == empresa_id, Usuario.activo.is_(True)
        )
        return self.db.execute(stmt).scalar_one()