# app/schemas/asignacion_taller.py
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CanalNotificacion, EstadoAsignacion
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
    # Para arreglar un precio mal digitado en el producto DESPUÉS de haber
    # asignado. Corrige solo esta asignación, no toca el catálogo.
    precio_unitario: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class DevolucionOut(TimestampSchema):
    """Una entrega concreta del taller. La lista completa reconstruye el
    historial que antes se perdía al guardar solo el acumulado."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    cantidad: int
    fecha: datetime


class AsignacionTallerOut(TimestampSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    lote_id: int
    cantidad_asignada: int
    fecha_asignacion: date
    cantidad_devuelta: int | None
    fecha_devolucion: datetime | None
    # Precio por unidad congelado al crear la asignación (copiado del tipo de
    # producto). Viaja como texto en el JSON: "1500.00". None si la empresa
    # no maneja precios o si el producto no tenía uno cargado ese día.
    precio_unitario: Decimal | None
    estado: EstadoAsignacion
    taller: TallerOut
    # No son columnas reales -- se calculan en el service (suma de incidencias
    # y asignada - devuelta - merma) y nunca se derivan en el front.
    cantidad_merma: int
    cantidad_pendiente: int
    # True solo si el ÚLTIMO intento de mandarle la ficha técnica al taller
    # fue exitoso -- False también cuando todavía no se ha intentado. Si es
    # False, el front puede ofrecer POST /asignaciones/{id}/reenviar-notificacion.
    notificacion_enviada: bool
    # Por dónde se entregó: "whatsapp" o "correo" (el respaldo). None si
    # todavía no se ha logrado entregar.
    canal_notificacion: CanalNotificacion | None
    # Cada entrega parcial por separado, de la más vieja a la más reciente.
    devoluciones: list[DevolucionOut] = []