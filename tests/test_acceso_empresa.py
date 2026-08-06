# tests/test_acceso_empresa.py
"""
El interruptor de pago: una empresa con `activo = False` no puede usar el
sistema, y -- lo más importante -- no puede reactivarse sola.
"""
import pytest
from sqlalchemy.orm import Session

from app.core.deps import get_current_usuario
from app.core.exceptions import ForbiddenError
from app.core.security import create_access_token
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.schemas.auth import LoginRequest
from app.schemas.empresa import EmpresaUpdate
from app.services.auth_service import AuthService
from app.services.empresa_service import EmpresaService
from tests.conftest import PASSWORD_DE_PRUEBA


def test_empresa_nueva_arranca_pausada(db: Session):
    """Nadie debe poder registrarse y empezar a usar el sistema sin pagar."""
    empresa = Empresa(nombre="Recién Registrada")
    db.add(empresa)
    db.commit()
    assert empresa.activo is False


def test_admin_no_puede_reactivar_su_propia_empresa(db: Session, empresa: Empresa):
    """Regresión de una vulnerabilidad real: `activo` estaba en EmpresaUpdate,
    así que el admin de una empresa pausada por falta de pago se reactivaba
    solo con un PATCH /empresas/actual (ese endpoint pide rol admin, y todo
    cliente es admin de su propia empresa)."""
    empresa.activo = False
    db.commit()

    EmpresaService(db).actualizar(empresa.id, EmpresaUpdate(activo=True))

    db.refresh(empresa)
    assert empresa.activo is False, "la empresa se reactivó sola: el cobro no está protegido"


def test_admin_si_puede_cambiar_el_nombre(db: Session, empresa: Empresa):
    """Blindar `activo` no debe romper la edición legítima."""
    EmpresaService(db).actualizar(empresa.id, EmpresaUpdate(nombre="Nombre Corregido"))

    db.refresh(empresa)
    assert empresa.nombre == "Nombre Corregido"


def test_login_bloqueado_si_la_empresa_esta_pausada(db: Session, empresa: Empresa, admin: Usuario):
    empresa.activo = False
    db.commit()

    with pytest.raises(ForbiddenError):
        AuthService(db).autenticar(
            LoginRequest(email=admin.email, password=PASSWORD_DE_PRUEBA)
        )


def test_sesion_ya_abierta_se_corta_al_pausar(db: Session, empresa: Empresa, admin: Usuario):
    """Pausar debe tener efecto inmediato, sin esperar a que venza el access
    token de quien ya estaba adentro."""
    token = create_access_token(subject=str(admin.id), empresa_id=empresa.id, rol=admin.rol.value)
    assert get_current_usuario(token=token, db=db).id == admin.id

    empresa.activo = False
    db.commit()

    with pytest.raises(ForbiddenError):
        get_current_usuario(token=token, db=db)


def test_reactivar_devuelve_el_acceso(db: Session, empresa: Empresa, admin: Usuario):
    empresa.activo = False
    db.commit()
    empresa.activo = True
    db.commit()

    usuario = AuthService(db).autenticar(
        LoginRequest(email=admin.email, password=PASSWORD_DE_PRUEBA)
    )
    assert usuario.id == admin.id
