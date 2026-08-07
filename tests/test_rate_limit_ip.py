# tests/test_rate_limit_ip.py
"""
Límite por IP en los endpoints públicos. Protege contra creación masiva de
cuentas y contra que alguien queme la cuota de correo (que se paga) pidiendo
recuperaciones en bucle.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.rate_limit import limpiar_ventanas_vencidas, obtener_ip, verificar_limite_ip
from app.models.intento_ip import IntentoIP

RUTA = "POST /auth/registro"


def _request(ip_directa: str | None = "1.2.3.4", reenviada: str | None = None) -> Mock:
    peticion = Mock()
    peticion.headers = {"x-forwarded-for": reenviada} if reenviada else {}
    peticion.client = Mock(host=ip_directa) if ip_directa else None
    return peticion


# --- Detección de la IP ---

def test_usa_la_ip_reenviada_por_el_proxy():
    """Detrás de Render y Cloudflare, la IP directa es la del proxy: sería la
    misma para todos y el límite bloquearía al mundo entero de golpe."""
    assert obtener_ip(_request(ip_directa="10.0.0.1", reenviada="200.1.2.3")) == "200.1.2.3"


def test_toma_el_primer_valor_de_la_cadena():
    """X-Forwarded-For acumula proxies; el cliente original es el primero."""
    assert obtener_ip(_request(reenviada="200.1.2.3, 10.0.0.1, 10.0.0.2")) == "200.1.2.3"


def test_sin_cabecera_usa_la_conexion_directa():
    assert obtener_ip(_request(ip_directa="1.2.3.4")) == "1.2.3.4"


# --- El límite ---

def test_deja_pasar_hasta_el_tope(db: Session):
    for _ in range(settings.IP_MAX_INTENTOS):
        verificar_limite_ip(db, "1.2.3.4", RUTA)


def test_bloquea_al_pasarse_del_tope(db: Session):
    for _ in range(settings.IP_MAX_INTENTOS):
        verificar_limite_ip(db, "1.2.3.4", RUTA)

    with pytest.raises(RateLimitedError) as error:
        verificar_limite_ip(db, "1.2.3.4", RUTA)
    # Retry-After: el cliente necesita saber cuándo reintentar.
    assert error.value.retry_after_seconds > 0


def test_cada_ip_lleva_su_propia_cuenta(db: Session):
    """Que un abusador agote su límite no puede dejar fuera a los demás."""
    for _ in range(settings.IP_MAX_INTENTOS):
        verificar_limite_ip(db, "1.1.1.1", RUTA)

    verificar_limite_ip(db, "2.2.2.2", RUTA)


def test_cada_ruta_lleva_su_propia_cuenta(db: Session):
    """Agotar el límite de recuperación de contraseña no debe impedirte
    registrarte."""
    for _ in range(settings.IP_MAX_INTENTOS):
        verificar_limite_ip(db, "1.2.3.4", "POST /auth/forgot-password")

    verificar_limite_ip(db, "1.2.3.4", "POST /auth/registro")


def test_la_ventana_se_reinicia_al_vencer(db: Session):
    for _ in range(settings.IP_MAX_INTENTOS):
        verificar_limite_ip(db, "1.2.3.4", RUTA)

    registro = db.execute(select(IntentoIP)).scalars().one()
    registro.ventana_inicio = datetime.now(timezone.utc) - timedelta(
        minutes=settings.IP_VENTANA_MINUTOS + 1
    )
    db.commit()

    verificar_limite_ip(db, "1.2.3.4", RUTA)
    db.refresh(registro)
    assert registro.intentos == 1


# --- Mantenimiento ---

def test_se_limpian_las_ventanas_viejas(db: Session):
    """Sin esto la tabla crece sin límite: una fila por cada IP que toque un
    endpoint público."""
    verificar_limite_ip(db, "1.2.3.4", RUTA)
    registro = db.execute(select(IntentoIP)).scalars().one()
    registro.ventana_inicio = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    limpiar_ventanas_vencidas(db)
    db.commit()

    assert db.execute(select(IntentoIP)).scalars().all() == []


def test_no_borra_las_ventanas_vigentes(db: Session):
    verificar_limite_ip(db, "1.2.3.4", RUTA)

    limpiar_ventanas_vencidas(db)
    db.commit()

    assert len(db.execute(select(IntentoIP)).scalars().all()) == 1
