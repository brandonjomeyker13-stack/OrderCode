# app/schemas/resumen.py
from pydantic import BaseModel

from app.schemas.taller import TallerOut


class ResumenGeneral(BaseModel):
    """Cifras del tablero principal, calculadas en la base de datos para que
    el front no tenga que traerse listados completos y sumarlos en memoria."""

    # asignado - devuelto - merma, de todo lo que sigue en poder de talleres.
    unidades_en_taller: int
    # Acumulado histórico de todo lo que los talleres han entregado.
    unidades_devueltas: int
    # Solo lo entregado hoy. Sale de los eventos de devolución, así que
    # cuenta la entrega del día y no el acumulado de la asignación.
    unidades_devueltas_hoy: int
    # Acumulado histórico de unidades dañadas (no vuelven al stock).
    unidades_en_merma: int
    talleres_activos: int
    lotes_pendientes_de_asignar: int
    asignaciones_abiertas: int


class ResumenTaller(BaseModel):
    """Mismas cifras, acotadas a un solo taller."""

    taller: TallerOut
    unidades_en_taller: int
    unidades_devueltas: int
    unidades_en_merma: int
    # Asignaciones que este taller todavía no termina de entregar.
    asignaciones_abiertas: int
    asignaciones_totales: int
    # Lotes distintos que tiene en curso ahora mismo.
    lotes_en_taller: int
    total_incidencias: int
