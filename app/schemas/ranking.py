# app/schemas/ranking.py
from datetime import date

from pydantic import BaseModel


class RankingTaller(BaseModel):
    """Lo que hizo un taller dentro del periodo consultado."""

    taller_id: int
    nombre: str
    numero_taller: str
    activo: bool

    # --- Cifras del periodo ---
    # Unidades que se le entregaron al taller entre las dos fechas.
    unidades_asignadas: int
    # Unidades buenas que devolvió en el periodo.
    unidades_devueltas: int
    # Unidades que se dañaron. No vuelven al stock.
    unidades_merma: int
    # Cuántas veces vino a entregar. Un taller que entrega en 6 tandas de 20
    # da más trabajo administrativo que uno que entrega 120 de una vez.
    entregas: int
    # merma / (devueltas + merma), en porcentaje. Mide calidad, no volumen:
    # así un taller chico y cuidadoso no queda mal parado frente a uno grande.
    tasa_merma: float
    # Días promedio entre asignar y recibir, sobre las entregas del periodo.
    # None cuando no hubo ninguna: un cero diría "entrega el mismo día".
    dias_promedio_entrega: float | None

    # --- Cifra de hoy, no del periodo ---
    # Lo que todavía tiene en su poder, sin importar cuándo se le asignó.
    unidades_pendientes: int


class RankingTalleres(BaseModel):
    """Comparativa de todos los talleres en un periodo.

    El periodo es un parámetro y no "el mes" porque cada empresa revisa con
    su propio ritmo: unas por quincena, otras por mes, otras por lote.
    """

    desde: date
    hasta: date
    talleres: list[RankingTaller]

    # Totales del periodo, para no obligar al front a sumar la tabla.
    total_unidades_devueltas: int
    total_unidades_merma: int
