# app/schemas/incidencia.py
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TipoIncidencia
from app.schemas.asignacion_taller import AsignacionTallerOut
from app.schemas.common import MAX_UNIDADES, TimestampSchema


class IncidenciaCreate(BaseModel):
    asignacion_id: int
    tipo: TipoIncidencia
    cantidad_afectada: int = Field(gt=0, le=MAX_UNIDADES)
    descripcion: str | None = Field(default=None, max_length=1000)
    fecha: date


class IncidenciaOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    asignacion_id: int
    tipo: TipoIncidencia
    cantidad_afectada: int
    descripcion: str | None
    fecha: date
    # Incluye el taller (asignacion.taller) para que el listado no requiera
    # una segunda llamada solo para saber a qué taller pertenece la incidencia.
    asignacion: AsignacionTallerOut