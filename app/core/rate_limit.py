# app/core/rate_limit.py
"""
Límite de llamadas por IP para los endpoints públicos.

El bloqueo de cuenta que ya existe en /auth/login protege UNA cuenta de que le
adivinen la contraseña. Esto es otra cosa: protege al servicio de alguien que
desde una misma IP crea cuentas en masa o pide mil recuperaciones de contraseña
para quemar la cuota de correo (que se paga).
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.models.intento_ip import IntentoIP

logger = logging.getLogger(__name__)


def obtener_ip(request: Request) -> str:
    """
    La IP real del cliente. Detrás de Render y Cloudflare, request.client.host
    es la del proxy y sería la misma para todo el mundo -- la verdadera viene
    en X-Forwarded-For, cuyo primer valor es el cliente original.

    Confiamos en esa cabecera porque solo se llega a la app a través de esos
    proxies. Si algún día se expone el backend directo a internet, deja de ser
    confiable (cualquiera la puede falsificar).
    """
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()[:45]
    return request.client.host if request.client else "desconocida"


def verificar_limite_ip(db: Session, ip: str, ruta: str) -> None:
    """
    Cuenta una llamada más de esta IP a esta ruta y lanza RateLimitedError
    (HTTP 429) si se pasó del límite dentro de la ventana.

    Cada ruta lleva su propia cuenta: agotar el límite de recuperación de
    contraseña no debería impedirte registrarte.
    """
    ahora = datetime.now(timezone.utc)
    ventana = timedelta(minutes=settings.IP_VENTANA_MINUTOS)

    registro = db.execute(
        select(IntentoIP).where(IntentoIP.ip == ip, IntentoIP.ruta == ruta)
    ).scalar_one_or_none()

    if registro is None:
        db.add(IntentoIP(ip=ip, ruta=ruta, intentos=1, ventana_inicio=ahora))
        try:
            db.commit()
        except IntegrityError:
            # Dos peticiones simultáneas de la misma IP crearon la fila a la
            # vez: el UNIQUE decide, y esta simplemente no cuenta. Preferible
            # a devolverle un error a alguien que no ha hecho nada malo.
            db.rollback()
        return

    inicio = registro.ventana_inicio
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)

    if ahora - inicio > ventana:
        registro.intentos = 1
        registro.ventana_inicio = ahora
        db.commit()
        return

    if registro.intentos >= settings.IP_MAX_INTENTOS:
        segundos = int((inicio + ventana - ahora).total_seconds()) + 1
        logger.warning("Límite por IP alcanzado: %s en %s", ip, ruta)
        raise RateLimitedError(
            "Demasiados intentos desde esta conexión. Espera unos minutos e intenta de nuevo.",
            retry_after_seconds=segundos,
        )

    registro.intentos += 1
    db.commit()


def limpiar_ventanas_vencidas(db: Session) -> int:
    """Borra los contadores cuya ventana ya pasó, para que la tabla no crezca
    sin límite. Se llama de forma oportunista, igual que las otras limpiezas."""
    from sqlalchemy import delete

    limite = datetime.now(timezone.utc) - timedelta(minutes=settings.IP_VENTANA_MINUTOS * 4)
    stmt = (
        delete(IntentoIP)
        .where(IntentoIP.ventana_inicio < limite)
        .execution_options(synchronize_session=False)
    )
    return db.execute(stmt).rowcount
