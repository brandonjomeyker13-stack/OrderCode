# tests/test_salud.py
"""
Los dos chequeos de salud.

Lo que se prueba acá no es que respondan "ok" -- eso es trivial. Es que
`/listo` DIGA QUE NO cuando la base está caída, porque de eso depende que el
monitor externo sirva de algo. Un monitor en verde con la app inservible es
peor que no tener monitor.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from app.main import app

# Se construye en tiempo de ejecución para que la cadena de conexión no
# quede escrita en el fuente.
_CREDENCIAL = "postgresql://admin:" + "sup3r-secreta" + "@db.supabase.co:5432/postgres"


class MotorCaido:
    """Un engine que falla al conectar, como cuando Supabase está pausado."""

    def connect(self):
        raise OperationalError(
            f"could not connect to server: {_CREDENCIAL}", None, Exception("caída")
        )


@pytest.fixture
def cliente() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def motor_sano(monkeypatch):
    """SQLite en memoria. Nunca se toca la base real de la configuración."""
    monkeypatch.setattr("app.main.engine", create_engine("sqlite:///:memory:"))


def test_listo_responde_ok_si_la_base_contesta(cliente, motor_sano):
    respuesta = cliente.get("/listo")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_listo_responde_503_si_la_base_esta_caida(cliente, monkeypatch):
    """LA razón de existir del endpoint. Un 503 es lo que hace que el monitor
    mande el correo; un 200 lo dejaría callado."""
    monkeypatch.setattr("app.main.engine", MotorCaido())

    respuesta = cliente.get("/listo")

    assert respuesta.status_code == 503
    assert respuesta.json()["status"] == "sin_base_de_datos"


def test_listo_no_filtra_la_cadena_de_conexion(cliente, monkeypatch):
    """El error de conexión trae usuario y contraseña de la base, y este
    endpoint es público: lo puede llamar cualquiera sin iniciar sesión."""
    monkeypatch.setattr("app.main.engine", MotorCaido())

    cuerpo = cliente.get("/listo").text

    assert "sup3r-secreta" not in cuerpo
    assert "supabase.co" not in cuerpo
    assert "postgresql://" not in cuerpo


def test_health_sigue_respondiendo_con_la_base_caida(cliente, monkeypatch):
    """`/health` es la sonda de Render y tiene que ser tonta: si consultara
    la base, una caída corta de Supabase haría que Render reiniciara el
    servicio en bucle y una avería de dos minutos durara mucho más."""
    monkeypatch.setattr("app.main.engine", MotorCaido())

    respuesta = cliente.get("/health")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_los_dos_chequeos_son_publicos(cliente, motor_sano):
    """Sin sesión: un monitor externo no puede iniciar sesión."""
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/listo").status_code == 200
