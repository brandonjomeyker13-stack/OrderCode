# app/db/session.py
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # evita errores por conexiones muertas (importante en Supabase/Render)
    pool_size=5,
    max_overflow=10,
    echo=settings.DEBUG,  # loguea SQL en desarrollo, apagado en producción
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency de FastAPI para inyectar una sesión de DB por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()