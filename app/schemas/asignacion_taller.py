# app/schemas/asignacion_taller.py
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CanalNotificacion, EstadoAsignacion
from app.schemas.common import MAX_UNIDADES, TimestampSchema
from app.schemas.taller import TallerOut


class AsignacionCorteCreate(BaseModel):
    """Proporciones de UNA prenda del corte, con todos sus colores.

    Leguins y shorts son proporciones distintas aunque salgan del mismo tendido.
    """

    corte_id: int
    tipo_producto_id: int
    taller_id: int
    proporciones: int = Field(gt=0, le=1000)
    fecha_asignacion: date


class AsignacionTallerCreate(BaseModel):
    lote_id: int
    taller_id: int
    #: Flujo viejo, o equivalente en unidades. En un lote por proporciones
    #: tiene que ser un múltiplo de las capas de ese color.
    cantidad_asignada: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)
    #: Cuántas proporciones enteras salen a este taller. En el flujo nuevo
    #: es la cifra que se teclea: unidades = proporciones × capas_color.
    proporciones: int | None = Field(default=None, gt=0, le=1000)
    fecha_asignacion: date

    @model_validator(mode="after")
    def _algo_se_asigna(self) -> "AsignacionTallerCreate":
        if self.cantidad_asignada is None and self.proporciones is None:
            raise ValueError("Indica las proporciones o las unidades que salen al taller")
        return self


class AsignacionTallerRegistrarDevolucion(BaseModel):
    """Se usa en el endpoint específico de 'registrar devolución', no en un
    update genérico, porque este evento tiene reglas propias (ver service)."""
    cantidad_devuelta: int = Field(ge=0, le=MAX_UNIDADES)
    fecha_devolucion: datetime


class AsignacionTallerUpdate(BaseModel):
    """Corrección de un error de captura -- solo se permite mientras la
    asignación sigue "pristina" (sin devolución ni merma registrada)."""
    taller_id: int | None = None
    cantidad_asignada: int | None = Field(default=None, gt=0, le=MAX_UNIDADES)
    fecha_asignacion: date | None = None


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


class EnvioCorteOut(BaseModel):
    """Lo que salió de un envío por corte: una fila por línea, juntas."""

    asignaciones: list[AsignacionTallerOut]
    unidades: int