# app/repositories/idempotency_key_repository.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.idempotency_key import IdempotencyKey


class IdempotencyKeyRepository:
    def __init__(self, db: Session):
        self.db = db

    def buscar(self, empresa_id: int, clave: str) -> IdempotencyKey | None:
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.empresa_id == empresa_id,
            IdempotencyKey.clave == clave,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def registrar(
        self, empresa_id: int, clave: str, ruta: str, recurso_tipo: str, recurso_id: int
    ) -> IdempotencyKey:
        registro = IdempotencyKey(
            empresa_id=empresa_id,
            clave=clave,
            ruta=ruta,
            recurso_tipo=recurso_tipo,
            recurso_id=recurso_id,
        )
        self.db.add(registro)
        self.db.flush()
        return registro
