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
from app.models.enums import EstadoLote, RolUsuario
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.schemas.corte import ColorCreate, CorteCreate, LineaCorteCreate
from app.schemas.inventario import VentaCreate, VentaUpdate
from app.schemas.recepcion import ConteoCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.color_service import ColorService
from app.services.corte_service import CorteService
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
    assert resumen.lineas[0].producto == "Producto de Prueba"
    assert [tanda.lote_id for tanda in resumen.lineas[0].tandas] == [lote.id]


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


# --- Los colores se venden por separado ---


def test_dos_colores_del_mismo_producto_son_dos_filas_que_se_venden_aparte(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte, ventas
):
    """Del mismo tendido salen el negro y el blanco, y cada uno es su propia
    línea: quien despacha tiene que ver de qué color hay y cuántos, y sacar de
    uno no puede tocar el otro. Sin el color en la respuesta son dos filas
    idénticas y se despacha a ciegas."""
    negro = ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro"))
    blanco = ColorService(db).crear(empresa.id, ColorCreate(nombre="Blanco"))
    qr = QRCode(empresa_id=empresa.id, token="token-colores")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id, nombre="Legging", referencia="LEG-01", qr_code_id=qr.id
    )
    db.add(tipo)
    db.commit()

    tendido = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=SALIDA,
            lineas=[
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=30),
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=blanco.id, cantidad=20),
            ],
        ),
    )
    por_color = {linea.color: linea.lote_id for linea in tendido.lineas}
    for color, cantidad in (("Negro", 30), ("Blanco", 20)):
        envio = AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=por_color[color],
                taller_id=taller.id,
                cantidad_asignada=cantidad,
                fecha_asignacion=SALIDA,
            ),
        )
        _recibir(db, empresa, envio, bodega, corte, buenas=cantidad)

    servicio = InventarioService(db)
    lineas = {linea.color: linea for linea in servicio.resumen(empresa.id).lineas}

    assert lineas["Negro"].cantidad_disponible == 30
    assert lineas["Blanco"].cantidad_disponible == 20
    assert [tanda.lote_id for tanda in lineas["Negro"].tandas] == [por_color["Negro"]], (
        "la fila trae la tanda de la que hay que descontar"
    )

    venta = servicio.registrar(
        empresa.id,
        VentaCreate(lote_id=por_color["Negro"], cantidad=10, fecha=VENTA),
        usuario_id=ventas.id,
    )

    assert venta.color == "Negro", "la salida dice de qué color salió"
    despues = {linea.color: linea for linea in servicio.resumen(empresa.id).lineas}
    assert despues["Negro"].cantidad_disponible == 20
    assert despues["Blanco"].cantidad_disponible == 20, "el otro color no se movió"


def test_el_mismo_color_en_dos_cortes_es_una_sola_fila(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte
):
    """Para vender, las negras son las negras: no importa de qué tendido
    salieron. Y la fila trae sus dos tandas, la vieja primero, porque la
    salida sí tiene que descontar de un lote concreto.

    El `limit=1` es media prueba: con la página por tanda, pedir una fila
    mostraba 30 negras cuando había 50, y las otras 20 quedaban en la página
    siguiente como si fueran otra cosa.
    """
    negro = ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro"))
    qr = QRCode(empresa_id=empresa.id, token="token-dos-cortes")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id, nombre="Buzo", referencia="BUZ-01", qr_code_id=qr.id
    )
    db.add(tipo)
    db.commit()

    lotes = []
    for fecha, cantidad in ((SALIDA, 30), (SALIDA + timedelta(days=3), 20)):
        tendido = CorteService(db).crear(
            empresa.id,
            CorteCreate(
                fecha=fecha,
                lineas=[
                    LineaCorteCreate(
                        tipo_producto_id=tipo.id, color_id=negro.id, cantidad=cantidad
                    )
                ],
            ),
        )
        lotes.append(tendido.lineas[0].lote_id)
        envio = AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=lotes[-1],
                taller_id=taller.id,
                cantidad_asignada=cantidad,
                fecha_asignacion=fecha,
            ),
        )
        _recibir(db, empresa, envio, bodega, corte, buenas=cantidad)

    resumen = InventarioService(db).resumen(empresa.id, offset=0, limit=1)

    assert resumen.total_lineas == 1, "un producto y un color son una sola fila"
    linea = resumen.lineas[0]
    assert linea.cantidad_disponible == 50, "las dos tandas suman en la misma fila"
    assert [tanda.lote_id for tanda in linea.tandas] == lotes, "la más vieja primero"
    assert [tanda.cantidad_disponible for tanda in linea.tandas] == [30, 20]


# --- El panorama: qué hay listo y qué viene en camino ---


def _tipo(db: Session, empresa: Empresa, nombre: str, referencia: str) -> TipoProducto:
    qr = QRCode(empresa_id=empresa.id, token=f"token-{referencia}")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id, nombre=nombre, referencia=referencia, qr_code_id=qr.id
    )
    db.add(tipo)
    db.commit()
    return tipo


def _cortar_y_enviar(db, empresa, taller, tipo, color, cantidad, fecha=SALIDA):
    """Un tendido de un solo color que sale entero al taller."""
    tendido = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=fecha,
            lineas=[
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=color.id, cantidad=cantidad)
            ],
        ),
    )
    lote_id = tendido.lineas[0].lote_id
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote_id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=fecha,
        ),
    )
    return lote_id, envio


def test_lo_que_sigue_en_el_taller_no_es_inventario_pero_si_panorama(
    db: Session, empresa: Empresa, taller: Taller
):
    """La razón de que el panorama exista.

    El inventario solo trae lo que se puede despachar, así que un color que
    acaba de salir al taller no aparece en ninguna parte -- y quien vende
    necesita saber que viene en camino para poder comprometer una entrega.
    """
    negro = ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro"))
    _cortar_y_enviar(db, empresa, taller, _tipo(db, empresa, "Buzo", "BUZ-P1"), negro, 40)
    servicio = InventarioService(db)

    assert servicio.resumen(empresa.id).lineas == [], "todavía no hay nada que despachar"

    panorama = servicio.panorama(empresa.id)
    assert panorama.total_en_proceso == 40
    assert panorama.total_disponible == 0
    assert [(l.color, l.cantidad_en_proceso, l.cantidad_disponible) for l in panorama.lineas] == [
        ("Negro", 40, 0)
    ]


def test_las_cifras_del_panorama_cuadran_con_lo_cortado(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte, ventas
):
    """cortada = en_proceso + perdida + disponible + vendida.

    Si deja de cuadrar, el panorama está mintiendo sobre dónde está la
    mercancía, que es lo único que esta pantalla tiene que hacer bien.
    """
    negro = ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro"))
    lote_id, envio = _cortar_y_enviar(
        db, empresa, taller, _tipo(db, empresa, "Buzo", "BUZ-P2"), negro, 100
    )
    # Llegan 60 buenas y 10 dañadas; 30 se quedaron en el taller.
    _recibir(db, empresa, envio, bodega, corte, buenas=60, danadas=10)
    servicio = InventarioService(db)
    servicio.registrar(
        empresa.id, VentaCreate(lote_id=lote_id, cantidad=25, fecha=VENTA), usuario_id=ventas.id
    )

    linea = servicio.panorama(empresa.id).lineas[0]

    assert linea.cantidad_cortada == 100
    assert linea.cantidad_en_proceso == 30, "lo que el taller no ha devuelto"
    assert linea.cantidad_perdida == 10, "lo dañado no vuelve ni sigue en el taller"
    assert linea.cantidad_disponible == 35
    assert linea.cantidad_vendida == 25
    assert linea.cantidad_cortada == (
        linea.cantidad_en_proceso
        + linea.cantidad_perdida
        + linea.cantidad_disponible
        + linea.cantidad_vendida
    )


def test_lo_cortado_entregado_y_vendido_entero_sale_del_panorama(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte, ventas
):
    """Se lee para decidir hoy: una tanda que ya se vendió completa es
    historia y solo ocuparía sitio."""
    negro = ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro"))
    agotado, envio = _cortar_y_enviar(
        db, empresa, taller, _tipo(db, empresa, "Buzo", "BUZ-P3"), negro, 20
    )
    _recibir(db, empresa, envio, bodega, corte, buenas=20)
    servicio = InventarioService(db)
    servicio.registrar(
        empresa.id, VentaCreate(lote_id=agotado, cantidad=20, fecha=VENTA), usuario_id=ventas.id
    )

    panorama = servicio.panorama(empresa.id)

    assert panorama.lineas == []
    assert panorama.total_lineas == 0


# --- Paginación: la página no puede cambiar los totales ---


def _tanda_lista(db, empresa, taller, bodega, corte, referencia, cantidad):
    """Un lote nuevo que ya volvió del taller y está confirmado."""
    qr = QRCode(empresa_id=empresa.id, token=f"token-{referencia}")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id,
        nombre=f"Producto {referencia}",
        referencia=referencia,
        qr_code_id=qr.id,
    )
    db.add(tipo)
    db.flush()
    lote = Lote(
        empresa_id=empresa.id,
        tipo_producto_id=tipo.id,
        cantidad_total=cantidad,
        fecha_registro=date(2026, 1, 10),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    db.add(lote)
    db.commit()

    asignacion = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=SALIDA,
        ),
    )
    _recibir(db, empresa, asignacion, bodega, corte, buenas=cantidad)
    return lote


def test_los_totales_son_de_la_empresa_y_no_de_la_pagina(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte
):
    """El bug que esto cierra: sumar solo la página hacía que pedir la segunda
    mostrara un inventario distinto al de la primera, y con muchos lotes el
    total salía en una fracción de lo que había."""
    for i in range(5):
        _tanda_lista(db, empresa, taller, bodega, corte, f"REF-P{i}", 10)

    pagina = InventarioService(db).resumen(empresa.id, offset=0, limit=2)

    assert len(pagina.lineas) == 2, "la página debe respetar el límite"
    assert pagina.total_lineas == 5, "hay cinco combinaciones de prenda y color"
    assert pagina.total_disponible == 50, "el total es de la empresa, no de la página"


def test_los_lotes_agotados_no_gastan_espacio_en_la_pagina(
    db: Session, empresa: Empresa, taller: Taller, bodega, corte, ventas
):
    """Antes se paginaban todos los lotes y después se descartaban los que no
    tenían nada: con historia suficiente, la primera página salía vacía y el
    inventario parecía estar en cero."""
    servicio = InventarioService(db)
    for i in range(3):
        agotado = _tanda_lista(db, empresa, taller, bodega, corte, f"REF-V{i}", 10)
        servicio.registrar(
            empresa.id,
            VentaCreate(lote_id=agotado.id, cantidad=10, fecha=VENTA),
            usuario_id=ventas.id,
        )
    con_stock = _tanda_lista(db, empresa, taller, bodega, corte, "REF-VIVO", 7)

    pagina = servicio.resumen(empresa.id, offset=0, limit=2)

    assert [
        tanda.lote_id for linea in pagina.lineas for tanda in linea.tandas
    ] == [con_stock.id]
    assert pagina.total_disponible == 7
    assert pagina.total_vendido == 30, "lo vendido es el histórico completo"


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
