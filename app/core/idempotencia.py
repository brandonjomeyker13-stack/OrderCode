# app/core/idempotencia.py
from sqlalchemy.orm import Session

from app.repositories.idempotency_key_repository import IdempotencyKeyRepository


def resolver_recurso_previo(db: Session, empresa_id: int, clave: str | None) -> tuple[str, int] | None:
    """Si esta `Idempotency-Key` ya se procesó, devuelve (recurso_tipo,
    recurso_id) para reconstruir la respuesta sin repetir la operación
    (crear otra fila, sumar otra devolución, etc). None si es la primera vez
    o si no se mandó clave -- en ese caso el endpoint sigue como siempre."""
    if not clave:
        return None
    registro = IdempotencyKeyRepository(db).buscar(empresa_id, clave)
    if registro is None:
        return None
    return registro.recurso_tipo, registro.recurso_id


def reclamar_clave(
    db: Session, empresa_id: int, clave: str | None, ruta: str, recurso_tipo: str, recurso_id: int
) -> None:
    """Registra la clave en la MISMA transacción que el cambio de negocio
    (el caller hace el commit después) -- así el recurso y su clave quedan
    atómicos: o se confirman los dos, o ninguno."""
    if not clave:
        return
    IdempotencyKeyRepository(db).registrar(empresa_id, clave, ruta, recurso_tipo, recurso_id)
