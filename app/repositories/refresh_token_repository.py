# app/repositories/refresh_token_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    """
    No hereda de BaseRepository: se filtra por usuario_id, no por empresa_id
    directamente (aunque en la práctica un usuario ya pertenece a una sola
    empresa, la relación de este token es con el usuario, no el tenant).
    """

    def __init__(self, db: Session):
        self.db = db

    def create(self, token: RefreshToken) -> RefreshToken:
        self.db.add(token)
        self.db.flush()
        self.db.refresh(token)
        return token

    def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def revocar(self, token_hash: str) -> bool:
        token = self.get_by_hash(token_hash)
        if token is None:
            return False
        token.revoked = True
        self.db.flush()
        return True

    def revocar_todos_de_usuario(self, usuario_id: int) -> None:
        """Usado en cambio de contraseña o logout de todos los dispositivos."""
        stmt = select(RefreshToken).where(
            RefreshToken.usuario_id == usuario_id,
            RefreshToken.revoked.is_(False),
        )
        tokens = self.db.execute(stmt).scalars().all()
        for t in tokens:
            t.revoked = True
        self.db.flush()

    def es_valido(self, token: RefreshToken) -> bool:
        return not token.revoked and token.expires_at > datetime.now(timezone.utc)