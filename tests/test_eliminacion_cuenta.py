# tests/test_eliminacion_cuenta.py
"""
Derecho de supresión: pedir la baja de la cuenta, arrepentirse dentro del
plazo, y que la purga borre TODO lo personal sin tocar a otras empresas.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import UnauthorizedError, ValidationError
from app.core.security import hash_password
from app.models.asignacion_taller import AsignacionTaller
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.empresa_eliminada import EmpresaEliminada
from app.models.enums import EstadoLote, RolUsuario
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.empresa_service import EmpresaService
from tests.conftest import PASSWORD_DE_PRUEBA


def _vencer_el_plazo(db: Session, empresa: Empresa) -> None:
    """Envejece la solicitud para no esperar 30 días de verdad."""
    empresa.eliminacion_solicitada_at = datetime.now(timezone.utc) - timedelta(
        days=settings.ELIMINACION_CUENTA_DIAS_GRACIA + 1
    )
    db.commit()


def _contar(db: Session, modelo) -> int:
    return db.execute(select(func.count()).select_from(modelo)).scalar_one()


# --- Solicitud ---

def test_solicitar_eliminacion_no_borra_nada_todavia(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote
):
    EmpresaService(db).solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)

    db.refresh(empresa)
    assert empresa.eliminacion_solicitada_at is not None
    assert _contar(db, Lote) == 1, "la ventana de gracia debe conservar los datos"
    assert _contar(db, Usuario) == 1


def test_solicitar_eliminacion_exige_la_contrasena(
    db: Session, empresa: Empresa, admin: Usuario
):
    """Sin esto, una sesión abierta en un equipo desatendido bastaría para
    destruir toda la operación de la empresa."""
    with pytest.raises(UnauthorizedError):
        EmpresaService(db).solicitar_eliminacion(empresa.id, admin, "contrasena-equivocada")

    db.refresh(empresa)
    assert empresa.eliminacion_solicitada_at is None


def test_no_se_puede_solicitar_dos_veces(db: Session, empresa: Empresa, admin: Usuario):
    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)

    with pytest.raises(ValidationError):
        servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)


# --- Cancelación ---

def test_se_puede_cancelar_dentro_del_plazo(db: Session, empresa: Empresa, admin: Usuario):
    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)

    servicio.cancelar_eliminacion(empresa.id)

    db.refresh(empresa)
    assert empresa.eliminacion_solicitada_at is None


def test_cancelar_evita_la_purga(db: Session, empresa: Empresa, admin: Usuario, lote: Lote):
    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)
    _vencer_el_plazo(db, empresa)
    servicio.cancelar_eliminacion(empresa.id)

    assert servicio.purgar_empresas_vencidas() == []
    assert _contar(db, Lote) == 1


def test_cancelar_sin_solicitud_previa_falla(db: Session, empresa: Empresa):
    with pytest.raises(ValidationError):
        EmpresaService(db).cancelar_eliminacion(empresa.id)


# --- Purga ---

def test_la_purga_respeta_la_ventana_de_gracia(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote
):
    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)

    assert servicio.purgar_empresas_vencidas() == [], "purgó antes de tiempo"
    assert _contar(db, Empresa) == 1


def test_la_purga_borra_todos_los_datos_personales(
    db: Session, empresa: Empresa, admin: Usuario, lote: Lote, taller: Taller
):
    """Lo importante: que no quede ningún dato identificable de nadie --
    ni del usuario, ni del taller (que puede ser una persona natural)."""
    empresa_id = empresa.id
    AsignacionTallerService(db).crear(
        empresa_id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=50,
            fecha_asignacion=date(2026, 2, 1),
        ),
    )
    db.add(Cliente(empresa_id=empresa_id, nombre="Cliente Mayorista", telefono="3009998877"))
    db.commit()

    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa_id, admin, PASSWORD_DE_PRUEBA)
    _vencer_el_plazo(db, empresa)

    assert servicio.purgar_empresas_vencidas() == [empresa_id]

    for modelo in (
        Empresa, Usuario, Taller, Cliente, Lote, TipoProducto, QRCode, AsignacionTaller
    ):
        assert _contar(db, modelo) == 0, f"quedaron filas en {modelo.__tablename__}"


def test_la_purga_deja_el_rastro_anonimizado(
    db: Session, empresa: Empresa, admin: Usuario
):
    """El deber contable obliga a conservar un registro, pero sin datos
    personales (ver EmpresaEliminada)."""
    empresa_id = empresa.id
    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa_id, admin, PASSWORD_DE_PRUEBA)
    _vencer_el_plazo(db, empresa)
    servicio.purgar_empresas_vencidas()

    rastro = db.execute(select(EmpresaEliminada)).scalars().one()
    assert rastro.empresa_id_original == empresa_id
    assert rastro.fecha_purga is not None

    columnas = {c.name for c in EmpresaEliminada.__table__.columns}
    assert "nombre" not in columnas
    assert "email" not in columnas


def test_la_purga_no_toca_a_otras_empresas(db: Session, empresa: Empresa, admin: Usuario):
    """Lo peor que podría pasar: borrar la cuenta equivocada."""
    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.flush()
    db.add(
        Usuario(
            empresa_id=otra.id,
            nombre="Admin Vecino",
            email="vecino@otra.com",
            password_hash=hash_password(PASSWORD_DE_PRUEBA),
            rol=RolUsuario.ADMIN,
        )
    )
    qr = QRCode(empresa_id=otra.id, token="token-vecino")
    db.add(qr)
    db.flush()
    db.add(
        TipoProducto(
            empresa_id=otra.id, nombre="Producto Vecino", referencia="REF-V", qr_code_id=qr.id
        )
    )
    db.commit()

    servicio = EmpresaService(db)
    servicio.solicitar_eliminacion(empresa.id, admin, PASSWORD_DE_PRUEBA)
    _vencer_el_plazo(db, empresa)
    servicio.purgar_empresas_vencidas()

    assert _contar(db, Empresa) == 1
    assert db.execute(select(Empresa)).scalars().one().id == otra.id
    assert _contar(db, Usuario) == 1
    assert _contar(db, TipoProducto) == 1
