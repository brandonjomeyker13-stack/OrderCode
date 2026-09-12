# tests/test_codigo_de_error.py
"""
Los dos 403 que no se parecen en nada.

"Tu empresa no tiene acceso" y "esta acción no es de tu puesto" comparten el
código HTTP y no comparten NADA más: el primero deja la aplicación entera
inservible hasta que el dueño pague, el segundo es un no de una sola pantalla
y el resto le sigue funcionando.

El front los trataba igual y le decía a la de bodega que la cuenta estaba
suspendida por falta de pago cada vez que tocaba un enlace que no era suyo.
El arreglo es `codigo`: un identificador que no cambia aunque se reescriba el
mensaje. Estas pruebas existen para que no se caiga sin que nadie lo note --
el front decide con él qué pantalla mostrar.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.exceptions import (
    EMPRESA_INACTIVA,
    ROL_INSUFICIENTE,
    ForbiddenError,
    NotFoundError,
)
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario


@pytest.fixture
def cliente(db: Session) -> TestClient:
    """TestClient con la sesión de prueba, no la real."""
    from app.db.session import get_db

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _token(usuario: Usuario) -> dict[str, str]:
    token = create_access_token(str(usuario.id), usuario.empresa_id, usuario.rol.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def bodega(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Jefa de Bodega",
        email="bodega@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.BODEGA,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


# --- La excepción ---


def test_un_error_sin_codigo_sigue_funcionando():
    """La mayoría de los errores no necesitan código: el mensaje basta. El
    campo es opcional para no tener que tocar los cincuenta sitios que ya
    lanzan errores."""
    error = NotFoundError("Asignación no encontrada")

    assert error.message == "Asignación no encontrada"
    assert error.codigo is None


def test_el_codigo_viaja_con_el_error():
    error = ForbiddenError("no es tuyo", codigo=ROL_INSUFICIENTE)

    assert error.codigo == ROL_INSUFICIENTE


# --- La respuesta HTTP ---


def test_el_403_por_puesto_dice_rol_insuficiente(cliente: TestClient, bodega: Usuario):
    """GET /lotes lleva cantidades y bodega cuenta a ciegas: el no es por
    puesto, y la aplicación le sigue sirviendo para lo suyo."""
    respuesta = cliente.get("/api/v1/lotes", headers=_token(bodega))

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == ROL_INSUFICIENTE


def test_el_403_por_empresa_pausada_dice_empresa_inactiva(
    cliente: TestClient, db: Session, empresa: Empresa, bodega: Usuario
):
    """Este sí deja la aplicación entera inservible, y es el único que el
    front debe mostrar como 'cuenta suspendida'."""
    empresa.activo = False
    db.commit()

    respuesta = cliente.get("/api/v1/lotes", headers=_token(bodega))

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == EMPRESA_INACTIVA


def test_la_empresa_pausada_gana_sobre_el_puesto(
    cliente: TestClient, db: Session, empresa: Empresa, bodega: Usuario
):
    """Con la empresa pausada, hasta una ruta que su puesto SÍ puede llamar
    tiene que responder lo mismo -- si no, el front mostraría media aplicación
    funcionando y media suspendida."""
    empresa.activo = False
    db.commit()

    respuesta = cliente.get("/api/v1/asignaciones", headers=_token(bodega))

    assert respuesta.status_code == 403
    assert respuesta.json()["codigo"] == EMPRESA_INACTIVA


def test_los_errores_de_siempre_no_ganaron_un_campo(cliente: TestClient, bodega: Usuario):
    """Regresión de forma: agregar `codigo` no debe meterlo en respuestas que
    no lo declaran. El front tiene un contrato de campos y una respuesta que
    crece sola es justo lo que tests/test_fugas_de_salida.py existe para
    impedir."""
    respuesta = cliente.get("/api/v1/asignaciones/99999", headers=_token(bodega))

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "Asignación no encontrada"}
