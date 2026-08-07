# app/core/fechas.py
"""
Manejo de "el día de hoy" para el negocio.

Todo se guarda en UTC, pero el usuario piensa en su día local. Mezclarlos
produce errores silenciosos: en Colombia (UTC-5), a las 8 de la noche el día
UTC ya avanzó y el local no, así que "lo devuelto hoy" contaría mal durante
las últimas horas de cada jornada -- justo cuando se cierra el día en planta.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


def zona() -> ZoneInfo:
    return ZoneInfo(settings.ZONA_HORARIA)


def hoy_local() -> date:
    """El día de hoy según la zona horaria del negocio, no la del servidor
    (Render corre en UTC) ni la de quien ejecute un script."""
    return datetime.now(zona()).date()


def rango_utc_del_dia(dia: date) -> tuple[datetime, datetime]:
    """Instantes UTC en que empieza y termina ese día local.

    Devuelve el intervalo como [inicio, fin) -- fin exclusivo -- para poder
    filtrar sin dejar fuera ni duplicar los eventos del último segundo.
    """
    inicio_local = datetime.combine(dia, time.min, tzinfo=zona())
    fin_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fin_local.astimezone(timezone.utc)
