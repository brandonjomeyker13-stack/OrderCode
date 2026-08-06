# tests/conftest.py
"""
Fixtures compartidas. Cada test corre contra una base SQLite en memoria
nueva, así ninguno depende del estado que dejó otro ni toca la base real.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  -- registra todos los modelos en Base.metadata
from app.core.security import hash_password
from app.db.base import Base
from app.models.empresa import Empresa
from app.models.enums import EstadoLote, RolUsuario
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario

PASSWORD_DE_PRUEBA = "clave-de-prueba-123"


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sesion = sessionmaker(bind=engine)()
    try:
        yield sesion
    finally:
        sesion.close()


@pytest.fixture
def empresa(db: Session) -> Empresa:
    """Empresa ya activada (el caso normal de un cliente que pagó)."""
    empresa = Empresa(nombre="Empresa de Prueba", activo=True)
    db.add(empresa)
    db.flush()
    return empresa


@pytest.fixture
def admin(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Admin de Prueba",
        email="admin@prueba.com",
        password_hash=hash_password(PASSWORD_DE_PRUEBA),
        rol=RolUsuario.ADMIN,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@pytest.fixture
def taller(db: Session, empresa: Empresa) -> Taller:
    taller = Taller(
        empresa_id=empresa.id,
        nombre="Taller de Prueba",
        numero_taller="T-001",
        telefono="3001234567",
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


@pytest.fixture
def lote(db: Session, empresa: Empresa) -> Lote:
    """Lote de 500 unidades listo para asignar a talleres."""
    qr = QRCode(empresa_id=empresa.id, token="token-de-prueba")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id, nombre="Producto de Prueba", referencia="REF-001", qr_code_id=qr.id
    )
    db.add(tipo)
    db.flush()
    lote = Lote(
        empresa_id=empresa.id,
        tipo_producto_id=tipo.id,
        cantidad_total=500,
        fecha_registro=date(2026, 1, 10),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    db.add(lote)
    db.commit()
    db.refresh(lote)
    return lote
