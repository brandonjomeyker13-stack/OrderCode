# tests/test_numero_taller.py
"""
El número de taller lo asigna el servidor: consecutivo por empresa, sin
repetirse y sin reutilizar números de talleres dados de baja.
"""
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.taller import Taller
from app.schemas.taller import TallerCreate
from app.services.taller_service import TallerService

DATOS = TallerCreate(nombre="Taller Nuevo", telefono="3001112233")


def test_el_primer_taller_arranca_en_001(db: Session, empresa: Empresa):
    taller = TallerService(db).crear(empresa.id, DATOS)
    assert taller.numero_taller == "001"


def test_los_numeros_van_en_orden(db: Session, empresa: Empresa):
    servicio = TallerService(db)
    numeros = [servicio.crear(empresa.id, DATOS).numero_taller for _ in range(3)]
    assert numeros == ["001", "002", "003"]


def test_el_cliente_no_puede_elegir_el_numero(db: Session, empresa: Empresa):
    """Aunque manden numero_taller en el body, se ignora."""
    datos = TallerCreate.model_validate(
        {"nombre": "Intruso", "telefono": "3001112233", "numero_taller": "999"}
    )
    taller = TallerService(db).crear(empresa.id, datos)
    assert taller.numero_taller == "001"


def test_cada_empresa_numera_desde_cero(db: Session, empresa: Empresa):
    """La unicidad es por empresa: que un cliente tenga el taller 001 no
    impide que otro también lo tenga."""
    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.commit()

    servicio = TallerService(db)
    primero = servicio.crear(empresa.id, DATOS)
    vecino = servicio.crear(otra.id, DATOS)

    assert primero.numero_taller == "001"
    assert vecino.numero_taller == "001"


def test_no_se_reutiliza_el_numero_de_un_taller_dado_de_baja(
    db: Session, empresa: Empresa
):
    """Reutilizarlo volvería ambiguo el histórico de asignaciones viejas."""
    servicio = TallerService(db)
    primero = servicio.crear(empresa.id, DATOS)
    servicio.desactivar(primero.id, empresa.id)

    siguiente = servicio.crear(empresa.id, DATOS)
    assert siguiente.numero_taller == "002"


def test_convive_con_numeros_heredados_no_numericos(db: Session, empresa: Empresa):
    """Si la empresa ya tenía talleres cargados a mano con otro formato, no
    deben romper la generación."""
    db.add(
        Taller(
            empresa_id=empresa.id,
            nombre="Taller Viejo",
            numero_taller="T-A",
            telefono="3009998877",
        )
    )
    db.commit()

    taller = TallerService(db).crear(empresa.id, DATOS)
    assert taller.numero_taller == "001"


def test_continua_desde_el_mayor_numero_existente(db: Session, empresa: Empresa):
    db.add(
        Taller(
            empresa_id=empresa.id,
            nombre="Taller Previo",
            numero_taller="007",
            telefono="3009998877",
        )
    )
    db.commit()

    taller = TallerService(db).crear(empresa.id, DATOS)
    assert taller.numero_taller == "008"
