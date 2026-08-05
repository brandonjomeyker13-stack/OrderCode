# app/schemas/asignacion_taller.py
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EstadoAsignacion
from app.schemas.common import TimestampSchema
from app.schemas.taller import TallerOut


class AsignacionTallerCreate(BaseModel):
    lote_id: int
    taller_id: int
    cantidad_asignada: int = Field(gt=0)
    fecha_asignacion: date


class AsignacionTallerRegistrarDevolucion(BaseModel):
    """Se usa en el endpoint específico de 'registrar devolución', no en un
    update genérico, porque este evento tiene reglas propias (ver service)."""
    cantidad_devuelta: int = Field(ge=0)
    fecha_devolucion: datetime


class AsignacionTallerUpdate(BaseModel):
    """Corrección de un error de captura -- solo se permite mientras la
    asignación sigue "pristina" (sin devolución ni merma registrada)."""
    taller_id: int | None = None
    cantidad_asignada: int | None = Field(default=None, gt=0)
    fecha_asignacion: date | None = None


class AsignacionTallerOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    lote_id: int
    cantidad_asignada: int
    fecha_asignacion: date
    cantidad_devuelta: int | None
    fecha_devolucion: datetime | None
    estado: EstadoAsignacion
    taller: TallerOut
    # No son columnas reales -- se calculan en el service (suma de incidencias
    # y asignada - devuelta - merma) y nunca se derivan en el front.
    cantidad_merma: int
    cantidad_pendiente: int
    # True solo si el ÚLTIMO intento de mandar la ficha técnica por WhatsApp
    # fue exitoso -- False también cuando todavía no se ha intentado. Si es
    # False, el front puede ofrecer POST /asignaciones/{id}/reenviar-notificacion.
    notificacion_whatsapp_enviada: bool