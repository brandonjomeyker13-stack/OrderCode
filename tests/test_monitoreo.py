# tests/test_monitoreo.py
"""
Limpieza de datos sensibles antes de reportar a Sentry.

Conectar Sentry es trivial; lo que hay que probar es que NO se les vayan
credenciales ni datos de los clientes. Un fallo acá no rompe la app, así que
pasaría desapercibido hasta que alguien revisara qué hay guardado allá.
"""
from app.core.monitoreo import _limpiar, configurar_sentry


def _evento_con_peticion(**peticion) -> dict:
    return {"request": {"url": "https://api.orderscode.com/api/v1/auth/login", **peticion}}


def test_no_se_manda_el_cuerpo_de_la_peticion():
    """El caso más grave: /auth/login y /auth/registro llevan la contraseña en
    texto plano en el body."""
    evento = _evento_con_peticion(
        data={"email": "cliente@empresa.com", "password": "la-contrasena-real"}
    )

    limpio = _limpiar(evento, {})

    assert "data" not in limpio["request"]
    assert "la-contrasena-real" not in str(limpio)


def test_no_se_mandan_las_cookies():
    """La cookie lleva el refresh token: con eso alguien entra como el usuario."""
    evento = _evento_con_peticion(cookies={"refresh_token": "token-de-sesion-valido"})

    limpio = _limpiar(evento, {})

    assert "cookies" not in limpio["request"]
    assert "token-de-sesion-valido" not in str(limpio)


def test_se_quitan_las_cabeceras_con_credenciales():
    evento = _evento_con_peticion(
        headers={
            "Authorization": "Bearer un-access-token",
            "Cookie": "refresh_token=abc",
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        }
    )

    limpio = _limpiar(evento, {})
    cabeceras = limpio["request"]["headers"]

    assert "Authorization" not in cabeceras
    assert "Cookie" not in cabeceras
    # Las que sirven para diagnosticar y no son sensibles se conservan.
    assert cabeceras["User-Agent"] == "Mozilla/5.0"
    assert "un-access-token" not in str(limpio)


def test_se_omite_la_query_string():
    """Puede llevar el token de recuperación de contraseña."""
    evento = _evento_con_peticion(query_string="token=token-secreto-de-recuperacion")

    limpio = _limpiar(evento, {})

    assert "token-secreto-de-recuperacion" not in str(limpio)


def test_un_evento_sin_peticion_no_rompe():
    """Los errores de scripts (respaldo, alertas) no tienen request."""
    evento = {"exception": {"values": [{"type": "ValueError"}]}}

    assert _limpiar(evento, {}) == evento


def test_sin_dsn_no_se_activa():
    """En desarrollo y en los tests no debe reportarse nada."""
    configurar_sentry()  # settings.SENTRY_DSN es None en el entorno de tests


def test_no_se_filtra_nada_al_reportar_un_error_real(monkeypatch):
    """La prueba que de verdad importa: un error real atravesando la app, con
    credenciales en el body y en las cabeceras.

    Los tests de arriba sobre _limpiar pasaban y AUN ASÍ la contraseña se
    filtraba, porque viajaba en las variables locales del stack trace. Solo
    esta prueba de punta a punta lo detectó.
    """
    import json

    import sentry_sdk
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel
    from sentry_sdk.transport import Transport

    import app.core.config as config_module
    import app.core.monitoreo as monitoreo

    enviados = []

    class TransporteDePrueba(Transport):
        def capture_envelope(self, envelope):
            for item in envelope.items:
                enviados.append(item.payload.json)

        def flush(self, *args, **kwargs):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(
        config_module.settings, "SENTRY_DSN", "https://falsa@o0.ingest.sentry.io/0"
    )
    monkeypatch.setattr(config_module.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.0)

    init_original = sentry_sdk.init

    def init_interceptado(**kwargs):
        kwargs["transport"] = TransporteDePrueba()
        return init_original(**kwargs)

    monkeypatch.setattr(sentry_sdk, "init", init_interceptado)
    monitoreo.configurar_sentry()

    try:
        app_prueba = FastAPI()

        class Credenciales(BaseModel):
            email: str
            password: str

        @app_prueba.post("/auth/login")
        def login(data: Credenciales):
            raise RuntimeError("fallo simulado")

        # Los valores se arman en tiempo de ejecución a propósito: Sentry
        # adjunta las líneas de código del stack trace, así que un literal
        # escrito acá aparecería en el reporte y daría un falso positivo.
        # En producción el fuente dice `data.password`, nunca el valor.
        contrasena = "Contrasena" + "Secreta" + "123"
        token = "access" + "-token-" + "real"
        correo = "cliente" + "@" + "empresa.com"

        TestClient(app_prueba, raise_server_exceptions=False).post(
            "/auth/login",
            json={"email": correo, "password": contrasena},
            headers={"Authorization": f"Bearer {token}", "Cookie": "refresh_token=abc"},
        )
        sentry_sdk.flush()

        reportado = json.dumps(enviados, default=str)
        for secreto in (contrasena, token, correo):
            assert secreto not in reportado, f"se filtró a Sentry: {secreto}"

        # Y sin embargo el error sí llega: si no, el monitoreo no serviría.
        assert "fallo simulado" in reportado
    finally:
        # Deja el SDK apagado para no contaminar el resto de los tests.
        sentry_sdk.init(dsn=None)
