# tests/test_contexto_y_roles.py
"""
El contexto de la request y las guardias por rol.

`get_empresa_id` devuelve un entero, así que un endpoint que solo dependa de
él no puede saber quién pregunta -- y por lo tanto no puede devolverle menos
información a un rol que a otro. Eso es un requisito del producto, no un
lujo: bodega cuenta a ciegas y no debe recibir las cantidades enviadas.
`Contexto` es lo que lo hace posible.
"""
import pytest
from sqlalchemy.orm import Session

from app.api.v1.deps import Contexto, get_contexto, get_empresa_id
from app.core.deps import require_admin, requiere_roles
from app.core.exceptions import ForbiddenError
from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario


@pytest.fixture
def corte(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Encargada de Corte",
        email="corte@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.CORTE,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


# --- Contexto ---


def test_el_contexto_lleva_usuario_empresa_y_rol(admin: Usuario, empresa: Empresa):
    contexto = get_contexto(admin)

    assert contexto.usuario is admin
    assert contexto.empresa_id == empresa.id
    assert contexto.rol == RolUsuario.ADMIN
    assert contexto.es_admin is True


def test_el_contexto_de_un_no_admin_no_dice_admin(corte: Usuario):
    contexto = get_contexto(corte)

    assert contexto.es_admin is False
    assert contexto.tiene_rol(RolUsuario.CORTE) is True
    assert contexto.tiene_rol(RolUsuario.ADMIN) is False


def test_get_empresa_id_sigue_devolviendo_el_tenant(admin: Usuario, empresa: Empresa):
    """Regresión: 67 endpoints dependen de esta función. Ahora se deriva del
    contexto, pero tiene que seguir devolviendo exactamente lo mismo."""
    assert get_empresa_id(get_contexto(admin)) == empresa.id


def test_el_contexto_es_inmutable(admin: Usuario):
    """Frozen a propósito: si un endpoint pudiera reescribir el empresa_id del
    contexto, el aislamiento entre empresas dependería de que nadie lo haga."""
    contexto = get_contexto(admin)

    with pytest.raises(Exception):
        contexto.empresa_id = 999


# --- Guardias por rol ---


def test_la_guardia_deja_pasar_un_rol_permitido(corte: Usuario):
    guardia = requiere_roles(RolUsuario.CORTE)

    assert guardia(corte) is corte


def test_la_guardia_deja_pasar_cualquiera_de_varios_roles(
    admin: Usuario, corte: Usuario
):
    guardia = requiere_roles(RolUsuario.ADMIN, RolUsuario.CORTE)

    assert guardia(admin) is admin
    assert guardia(corte) is corte


def test_la_guardia_rechaza_un_rol_que_no_esta(corte: Usuario):
    guardia = requiere_roles(RolUsuario.ADMIN)

    with pytest.raises(ForbiddenError):
        guardia(corte)


def test_una_guardia_sin_roles_es_un_error_de_programacion():
    """Una guardia que no permite a nadie cerraría el endpoint para todos y el
    fallo aparecería en producción como un 403 inexplicable. Mejor reventar al
    importar el módulo."""
    with pytest.raises(ValueError):
        requiere_roles()


def test_require_admin_conserva_su_mensaje(corte: Usuario):
    """El texto lo ve el usuario y ya está en producción; el nombre lo
    declaran ~15 endpoints y tests/test_permisos.py lo comprueba por
    identidad. Reexpresarlo con la fábrica no debe cambiar ninguna de las dos
    cosas."""
    with pytest.raises(ForbiddenError) as excinfo:
        require_admin(corte)

    assert excinfo.value.message == "Esta acción requiere rol de administrador"


def test_require_admin_deja_pasar_al_admin(admin: Usuario):
    assert require_admin(admin) is admin
