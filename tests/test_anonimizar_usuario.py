# tests/test_anonimizar_usuario.py
"""
Supresión de datos personales de un usuario individual, sin borrar el
historial operativo (que le pertenece a la empresa, no a la persona).
"""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UnauthorizedError, ValidationError
from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.refresh_token import RefreshToken
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest
from app.schemas.usuario import UsuarioCreate
from app.services.auth_service import AuthService
from app.services.usuario_service import UsuarioService
from tests.conftest import PASSWORD_DE_PRUEBA


@pytest.fixture
def operario(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="María Operaria",
        email="maria@prueba.com",
        password_hash=hash_password(PASSWORD_DE_PRUEBA),
        rol=RolUsuario.OPERADOR,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def test_anonimizar_borra_los_datos_personales(
    db: Session, empresa: Empresa, admin: Usuario, operario: Usuario
):
    UsuarioService(db).anonimizar(operario.id, empresa.id)

    db.refresh(operario)
    assert "María" not in operario.nombre
    assert "maria@prueba.com" != operario.email
    assert operario.google_sub is None
    assert operario.activo is False


def test_la_cuenta_anonimizada_ya_no_puede_entrar(
    db: Session, empresa: Empresa, admin: Usuario, operario: Usuario
):
    UsuarioService(db).anonimizar(operario.id, empresa.id)

    with pytest.raises(UnauthorizedError):
        AuthService(db).autenticar(
            LoginRequest(email="maria@prueba.com", password=PASSWORD_DE_PRUEBA)
        )


def test_anonimizar_cierra_las_sesiones_abiertas(
    db: Session, empresa: Empresa, admin: Usuario, operario: Usuario
):
    auth = AuthService(db)
    _, token = auth.emitir_tokens(operario, ip=None, user_agent=None)

    UsuarioService(db).anonimizar(operario.id, empresa.id)

    with pytest.raises(UnauthorizedError):
        auth.refrescar_access_token(token)


def test_se_libera_el_correo_para_reutilizarlo(
    db: Session, empresa: Empresa, admin: Usuario, operario: Usuario
):
    """El correo tiene UNIQUE: si no se libera, esa persona no podría volver
    a registrarse nunca con su propio correo."""
    UsuarioService(db).anonimizar(operario.id, empresa.id)

    nuevo = UsuarioService(db).crear(
        empresa.id,
        UsuarioCreate(
            nombre="María Otra Vez",
            email="maria@prueba.com",
            password=PASSWORD_DE_PRUEBA,
            rol=RolUsuario.OPERADOR,
        ),
    )
    assert nuevo.email == "maria@prueba.com"


def test_se_pueden_anonimizar_varios_sin_chocar(
    db: Session, empresa: Empresa, admin: Usuario, operario: Usuario
):
    """El correo de reemplazo se deriva del id, así dos anonimizados no
    violan el UNIQUE."""
    otro = Usuario(
        empresa_id=empresa.id,
        nombre="Pedro Operario",
        email="pedro@prueba.com",
        password_hash=hash_password(PASSWORD_DE_PRUEBA),
        rol=RolUsuario.OPERADOR,
    )
    db.add(otro)
    db.commit()

    servicio = UsuarioService(db)
    servicio.anonimizar(operario.id, empresa.id)
    servicio.anonimizar(otro.id, empresa.id)

    db.refresh(operario)
    db.refresh(otro)
    assert operario.email != otro.email


# --- Guardia del último admin ---

def test_no_se_puede_anonimizar_al_unico_admin(db: Session, empresa: Empresa, admin: Usuario):
    """Sería irreversible y dejaría a la empresa sin nadie que la administre."""
    with pytest.raises(ValidationError):
        UsuarioService(db).anonimizar(admin.id, empresa.id)

    db.refresh(admin)
    assert admin.nombre == "Admin de Prueba"


def test_no_se_puede_desactivar_al_unico_admin(db: Session, empresa: Empresa, admin: Usuario):
    with pytest.raises(ValidationError):
        UsuarioService(db).desactivar(admin.id, empresa.id)

    db.refresh(admin)
    assert admin.activo is True


def test_si_hay_otro_admin_si_se_permite(db: Session, empresa: Empresa, admin: Usuario):
    segundo = Usuario(
        empresa_id=empresa.id,
        nombre="Segundo Admin",
        email="admin2@prueba.com",
        password_hash=hash_password(PASSWORD_DE_PRUEBA),
        rol=RolUsuario.ADMIN,
    )
    db.add(segundo)
    db.commit()

    UsuarioService(db).anonimizar(admin.id, empresa.id)

    db.refresh(admin)
    assert admin.activo is False
