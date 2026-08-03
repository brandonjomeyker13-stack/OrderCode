# app/db/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Clase base declarativa de SQLAlchemy 2.0.
    Todos los modelos en app/models/ heredan de esta clase.
    Alembic también apunta a Base.metadata para detectar cambios.
    """
    pass