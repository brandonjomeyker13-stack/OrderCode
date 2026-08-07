# app/schemas/ranking.py
from datetime import date
from decimal import Decimal

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
    # Unidades buenas que devolvió en el periodo. ESTA es la base de pago.
    unidades_devueltas: int
    # Unidades que se dañaron. No vuelven al stock ni se le pagan.
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

    # --- La plata ---
    # Suma de (unidades entregadas x precio congelado en su asignación).
    # Viaja como texto en el JSON: "510000.00".
    monto_a_pagar: Decimal
    # Unidades entregadas cuya asignación no tenía precio cargado. Si esto no
    # es cero, `monto_a_pagar` está incompleto y hay que decírselo al usuario
    # en pantalla en vez de dejar que pague de menos sin enterarse.
    unidades_sin_tarifa: int

    # --- Cifra de hoy, no del periodo ---
    # Lo que todavía tiene en su poder. Se incluye porque al momento de pagar
    # también se quiere ver quién está cargado de trabajo pendiente.
    unidades_pendientes: int


class RankingTalleres(BaseModel):
    """Comparativa de todos los talleres en un periodo.

    El periodo es un parámetro y no "el mes" porque cada empresa cierra
    distinto: unas pagan quincenal, otras mensual, otras por lote terminado.
    """

    desde: date
    hasta: date
    talleres: list[RankingTaller]

    # Totales del periodo, para no obligar al front a sumar la tabla.
    total_unidades_devueltas: int
    total_unidades_merma: int
    total_a_pagar: Decimal
    # Si es > 0, el total de arriba se queda corto: faltan precios por cargar.
    total_unidades_sin_tarifa: int
