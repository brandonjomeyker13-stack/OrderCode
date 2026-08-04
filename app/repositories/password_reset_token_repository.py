# app/repositories/password_reset_token_repository.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:
    """No hereda de BaseRepository: se filtra por usuario_id, igual que
    RefreshTokenRepository (ver ese archivo para la explicación)."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, token: PasswordResetToken) -> PasswordResetToken:
        self.db.add(token)
        self.db.flush()
        self.db.refresh(token)
        return token

    def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def es_valido(self, token: PasswordResetToken) -> bool:
        expires_at = token.expires_at
        # Algunos backends (ej. SQLite en tests) devuelven el datetime sin
        # tzinfo aunque la columna sea timezone=True -- siempre se escribe
        # en UTC, así que es seguro asumir UTC si viene naive.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return token.used_at is None and expires_at > datetime.now(timezone.utc)
