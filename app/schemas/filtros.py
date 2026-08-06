# app/schemas/filtros.py
from dataclasses import dataclass
from datetime import date

from app.models.enums import EstadoAsignacion


@dataclass(frozen=True)
class FiltrosAsignacion:
    """Filtros del listado de asignaciones. Se aplican en SQL, no en memoria:
    con volumen real, traerse todas las asignaciones de la empresa para
    filtrarlas en el cliente deja de ser viable.

    Todos opcionales: si no se manda ninguno, el listado se comporta igual
    que antes."""
    taller_id: int | None = None
    lote_id: int | None = None
    estado: EstadoAsignacion | None = None
    desde: date | None = None
    hasta: date | None = None
