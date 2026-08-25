# app/schemas/common.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict

# Tope de cualquier cantidad de unidades que entre por la API.
#
# Existe por una razón concreta: las columnas de cantidad son INTEGER en
# PostgreSQL, que aguanta hasta 2.147.483.647. Sin tope, un número mayor pasa
# la validación, llega a la base y revienta con un error 500 -- cuando debería
# ser un 422 diciendo que el número no tiene sentido.
#
# Los tests NO detectan eso: corren sobre SQLite, que no tiene ese límite.
#
# Diez millones está muy por encima de cualquier lote real de este negocio (el
# cliente más grande produce ~100.000 unidades AL MES) y muy por debajo del
# límite del motor, así que deja margen sin dejar pasar disparates.
MAX_UNIDADES = 10_000_000


class TimestampSchema(BaseModel):
    """Mixin de salida para created_at / updated_at, presente en casi toda respuesta."""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginationParams(BaseModel):
    """Query params reutilizables para listados paginados."""
    page: int = 1
    page_size: int = 50

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list