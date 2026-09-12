# tests/test_inventario.py
"""
El final del recorrido: lo que está listo, y sacarlo.

La regla que sostiene todo este archivo es que el disponible NO se guarda: se
calcula como lo devuelto y confirmado menos lo vendido. Por eso hay pruebas
que parecen raras -- borrar una salida devuelve las unidades, corregirla no se
pelea consigo misma -- y todas comprueban lo mismo desde ángulos distintos: que
no hay un saldo guardado que se pueda quedar viejo.

La otra regla, la que conecta con la recepción: un conteo que bodega registró
y corte todavía no confirmó NO es inventario. Mientras nadie lo revise, esas
prendas siguen contando como si estuvieran en el taller.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.lote import Lote
from app.models.taller import Taller
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.schemas.inventario import VentaCreate, VentaUpdate
from app.schemas.recepcion import ConteoCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.inventario_service import InventarioService
from app.services.recepcion.bodega import RecepcionBodegaService
from app.services.recepcion.corte import ConfirmacionCorteService

SALIDA = date(2026, 1, 15)
LLEGADA = SALIDA + timedelta(days=7)
VENTA = LLEGADA + timedelta(days=1)


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


@pytest.fixture
def corte(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Miriam",
        email="corte@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.CORTE,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@pytest.fixture
def ventas(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Quien Despacha",
        email="ventas@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.VENTAS,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@pytest.fixture
def asignacion(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """50 unidades salieron al taller."""
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=50,
            fecha_asignacion=SALIDA,
        ),
    )


def _recibir(db, empresa, asignacion, bodega, corte, buenas, danadas=0, confirmar=True):
    """El recorrido completo: bodega cuenta y corte confirma."""
    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=asignacion.id,
            cantidad_buena=buenas,
            cantidad_danada=danadas,
            fecha=LLEGADA,
        ),
        usuario_id=bodega.id,
    )
    if confirmar:
        ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)
    return conteo


# --- Qué llega al inventario ---


def test_sin_devoluciones_no_hay_inventario(db: Session, empresa: Empresa, asignacion):
    """El lote existe y está en el taller: todavía no hay nada que vender."""
    resumen = InventarioService(db).resumen(empresa.id)

    assert resumen.total_disponible == 0
    assert resumen.lineas == []


def test_lo_confirmado_aparece_como_disponible(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)

    resumen = InventarioService(db).resumen(empresa.id)

    assert resumen.total_disponible == 50
    assert len(resumen.lineas) == 1
    assert resumen.lineas[0].lote_id == lote.id
    assert resumen.lineas[0].producto == "Producto de Prueba"


def test_un_conteo_sin_confirmar_no_es_inventario(
    db: Session, empresa: Empresa, asignacion, bodega, corte
):
    """La prueba que une las dos etapas. Mientras corte no revise, para el
    sistema esas prendas siguen en el taller -- y esa es justamente la razón
    de que la confirmación exista."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50, confirmar=False)

    assert InventarioService(db).resumen(empresa.id).total_disponible == 0


def test_lo_danado_no_esta_listo_para_vender(
    db: Session, empresa: Empresa, asignacion, bodega, corte
):
    """Llegaron 50: 45 buenas y 5 dañadas. Solo las buenas son inventario."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=45, danadas=5)

    assert InventarioService(db).resumen(empresa.id).total_disponible == 45


# --- Sacar del inventario ---


def test_una_venta_descuenta_del_disponible(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)

    servicio.registrar(
        empresa.id,
        VentaCreate(lote_id=lote.id, cantidad=20, fecha=VENTA, nota="Pedido de la 93"),
        usuario_id=ventas.id,
    )

    resumen = servicio.resumen(empresa.id)
    assert resumen.total_disponible == 30
    assert resumen.total_vendido == 20
    assert resumen.lineas[0].cantidad_vendida == 20


def test_no_se_puede_vender_mas_de_lo_que_hay(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    """Este mensaje SÍ nombra la cifra, y puede: lo lee ventas. El conteo a
    ciegas es de bodega, no de este extremo del recorrido."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)

    with pytest.raises(ValidationError) as excinfo:
        InventarioService(db).registrar(
            empresa.id,
            VentaCreate(lote_id=lote.id, cantidad=51, fecha=VENTA),
            usuario_id=ventas.id,
        )

    assert "50" in excinfo.value.message


def test_el_lote_agotado_desaparece_del_inventario(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    """Un lote en cero no es inventario, es historia: se mira en la lista de
    salidas, no en la pantalla de lo que hay."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)
    servicio.registrar(
        empresa.id, VentaCreate(lote_id=lote.id, cantidad=50, fecha=VENTA), usuario_id=ventas.id
    )

    resumen = servicio.resumen(empresa.id)
    assert resumen.lineas == []
    assert resumen.total_vendido == 50


def test_quien_despacho_queda_escrito(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)

    venta = InventarioService(db).registrar(
        empresa.id, VentaCreate(lote_id=lote.id, cantidad=10, fecha=VENTA), usuario_id=ventas.id
    )

    assert venta.registrada_por == "Quien Despacha"
    assert venta.producto == "Producto de Prueba"


def test_el_doble_clic_no_saca_dos_veces(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)
    cuerpo = VentaCreate(lote_id=lote.id, cantidad=20, fecha=VENTA)

    primero = servicio.registrar(empresa.id, cuerpo, ventas.id, idempotency_key="clic-1")
    segundo = servicio.registrar(empresa.id, cuerpo, ventas.id, idempotency_key="clic-1")

    assert primero.id == segundo.id
    assert servicio.resumen(empresa.id).total_disponible == 30


# --- Corregirse ---


def test_corregir_una_venta_no_se_pelea_consigo_misma(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    """El caso que revienta si se compara mal: se vendieron 50 de 50 y se
    corrige a 49. El disponible de AHORA es 0, así que sin devolverle a la
    venta lo suyo antes de comparar, esto diría "no hay disponible" cuando en
    realidad sobra."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)
    venta = servicio.registrar(
        empresa.id, VentaCreate(lote_id=lote.id, cantidad=50, fecha=VENTA), usuario_id=ventas.id
    )

    corregida = servicio.actualizar(venta.id, empresa.id, VentaUpdate(cantidad=49))

    assert corregida.cantidad == 49
    assert servicio.resumen(empresa.id).total_disponible == 1


def test_corregir_por_encima_de_lo_que_hay_se_frena(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)
    venta = servicio.registrar(
        empresa.id, VentaCreate(lote_id=lote.id, cantidad=20, fecha=VENTA), usuario_id=ventas.id
    )

    with pytest.raises(ValidationError):
        servicio.actualizar(venta.id, empresa.id, VentaUpdate(cantidad=51))


def test_borrar_la_salida_devuelve_las_unidades(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega, corte, ventas
):
    """No hace falta "reponer" nada: el disponible se calcula, así que borrar
    la fila basta. Es la ventaja de no guardar el saldo."""
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    servicio = InventarioService(db)
    venta = servicio.registrar(
        empresa.id, VentaCreate(lote_id=lote.id, cantidad=20, fecha=VENTA), usuario_id=ventas.id
    )

    servicio.eliminar(venta.id, empresa.id)

    assert servicio.resumen(empresa.id).total_disponible == 50
    with pytest.raises(NotFoundError):
        servicio.obtener(venta.id, empresa.id)


# --- Aislamiento entre empresas ---


def test_una_empresa_no_ve_el_inventario_de_otra(
    db: Session, empresa: Empresa, asignacion, bodega, corte
):
    _recibir(db, empresa, asignacion, bodega, corte, buenas=50)
    otra = Empresa(nombre="Otra Empresa", activo=True)
    db.add(otra)
    db.commit()

    assert InventarioService(db).resumen(otra.id).total_disponible == 0
    assert InventarioService(db).listar_ventas(otra.id) == []
