# app/repositories/usuario_repository.py
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.repositories.base import BaseRepository


class UsuarioRepository(BaseRepository[Usuario]):
    def __init__(self, db: Session):
        super().__init__(Usuario, db)

    def emails_existentes(self, emails: list[str]) -> set[str]:
        """Cuáles de esos correos ya están tomados. El email es único en
        toda la base (no por empresa): el login ocurre antes de saber el
        tenant, igual que get_by_email."""
        if not emails:
            return set()
        claves = [e.strip().lower() for e in emails]
        stmt = select(func.lower(Usuario.email)).where(func.lower(Usuario.email).in_(claves))
        return {e for e in self.db.execute(stmt).scalars().all() if e}

    def get_by_email(self, email: str) -> Usuario | None:
        """
        Sin filtro de empresa_id a propósito: el login ocurre ANTES de saber
        a qué empresa pertenece la sesión -- el email es único globalmente
        (constraint en el modelo), así que esta es la única excepción
        legítima a la regla de oro. Se usa solo en el flujo de autenticación.
        """
        stmt = select(Usuario).where(Usuario.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def contar_otros_admins_activos(self, empresa_id: int, excluyendo_id: int) -> int:
        """Cuántos admins activos quedarían si se diera de baja a
        `excluyendo_id` -- si es 0, la empresa se quedaría sin nadie que
        pueda administrarla."""
        stmt = (
            select(func.count())
            .select_from(Usuario)
            .where(
                Usuario.empresa_id == empresa_id,
                Usuario.rol == RolUsuario.ADMIN,
                Usuario.activo.is_(True),
                Usuario.id != excluyendo_id,
            )
        )
        return self.db.execute(stmt).scalar_one()