# app/schemas/alerta.py
from datetime import date

from pydantic import BaseModel

from app.schemas.taller import TallerOut


class AsignacionAtrasada(BaseModel):
    """Una asignación que lleva demasiados días en el taller sin cerrarse."""

    asignacion_id: int
    lote_id: int
    taller: TallerOut
    producto: str
    referencia: str
    fecha_asignacion: date
    dias_fuera: int
    # Lo que realmente falta que el taller entregue: descuenta lo ya devuelto
    # y lo dado por perdido en merma.
    cantidad_pendiente: int


class ResumenAlertas(BaseModel):
    # A partir de cuántos días se considera atraso en esta empresa.
    dias_umbral: int
    total_atrasadas: int
    unidades_comprometidas: int
    # Días de la más vieja -- el peor caso, que es lo que interesa mirar.
    dias_del_mas_atrasado: int
    atrasadas: list[AsignacionAtrasada]
