# tests/test_recepcion.py
"""
La recepción a dos manos: bodega cuenta, corte confirma.

Lo que estas pruebas cuidan no es un formulario, es un control. Bodega cuenta
sin saber cuánto se envió; si su cifra no coincide, el sistema NO la rechaza
-- la deja anotada y se la muestra a corte con la diferencia calculada, para
que la conversación pase entre dos personas y no entre una persona y un
mensaje de error.

Por eso la prueba que más importa de este archivo es la primera: que un conteo
que no cuadra se guarde igual. El diseño anterior lo rechazaba con un 422 que
decía la cantidad exacta que faltaba, o sea que le enseñaba a bodega el número
que tenía que teclear para que lo aceptaran.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import EstadoAsignacion, EstadoConteo, EstadoLote, RolUsuario
from app.models.lote import Lote
from app.models.taller import Taller
from app.models.usuario import Usuario
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.schemas.recepcion import ConteoCreate, ConteoUpdate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.recepcion.bodega import RecepcionBodegaService
from app.services.recepcion.corte import ConfirmacionCorteService

SALIDA = date(2026, 1, 15)
LLEGADA = SALIDA + timedelta(days=7)


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


def _contar(db, empresa, asignacion, bodega, buenas, danadas=0, nota=None):
    return RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=asignacion.id,
            cantidad_buena=buenas,
            cantidad_danada=danadas,
            fecha=LLEGADA,
            nota=nota,
        ),
        usuario_id=bodega.id,
    )


# --- Lo que ve bodega ---


def test_la_lista_de_bodega_no_trae_ni_una_cantidad(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """El requisito del dueño en su forma más concreta: la pantalla desde la
    que bodega trabaja dice QUÉ puede llegar y nunca CUÁNTO."""
    pendientes = RecepcionBodegaService(db).listar_pendientes(empresa.id)

    assert len(pendientes) == 1
    publicado = pendientes[0].model_dump()
    assert not [campo for campo in publicado if "cantidad" in campo]
    # Pero sí lo que necesita para saber qué tiene delante.
    assert publicado["producto"] == "Producto de Prueba"
    assert publicado["taller"]["nombre"] == "Taller de Prueba"


def test_el_acuse_del_conteo_solo_repite_lo_que_bodega_tecleo(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    publicado = conteo.model_dump()
    assert publicado["cantidad_buena"] == 48
    assert "cantidad_asignada" not in publicado
    assert "cantidad_pendiente" not in publicado


# --- El corazón: un conteo que no cuadra se guarda ---


def test_un_conteo_que_no_cuadra_se_guarda_igual(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Salieron 50 y bodega cuenta 48. Antes esto era un 422 que decía "faltan
    2"; ahora queda anotado y la diferencia se la explica a corte."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    assert conteo.estado == EstadoConteo.REPORTADO


def test_bodega_puede_reportar_de_mas_sin_que_el_sistema_la_corrija(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Contar 60 de un envío de 50 es justo el caso que hay que poder
    registrar: es un error que alguien tiene que mirar, y el sistema no puede
    taparlo rechazándolo -- ni delatar de paso cuál era el número bueno."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=60)

    assert conteo.cantidad_buena == 60
    assert conteo.estado == EstadoConteo.REPORTADO


def test_el_reporte_no_mueve_el_saldo_del_taller(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Hasta que corte no confirme, para el resto del sistema no pasó nada.
    Si el reporte descontara saldo, un conteo equivocado ya habría cerrado la
    asignación antes de que nadie lo revisara."""
    _contar(db, empresa, asignacion, bodega, buenas=48)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert (fresca.cantidad_devuelta or 0) == 0
    assert fresca.estado == EstadoAsignacion.ASIGNADO


def test_un_conteo_vacio_no_es_un_conteo(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    with pytest.raises(ValueError):
        ConteoCreate(
            asignacion_id=asignacion.id, cantidad_buena=0, cantidad_danada=0, fecha=LLEGADA
        )


def test_la_fecha_anterior_a_la_salida_se_rechaza(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """La única validación del reporte, y no dice nada de cantidades."""
    with pytest.raises(ValidationError) as excinfo:
        RecepcionBodegaService(db).registrar(
            empresa.id,
            ConteoCreate(
                asignacion_id=asignacion.id,
                cantidad_buena=10,
                fecha=SALIDA - timedelta(days=1),
            ),
            usuario_id=bodega.id,
        )

    assert "anterior" in str(excinfo.value.message)


def test_el_envio_ya_cerrado_no_admite_otro_conteo(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """Ese envío ya no sale en la lista de bodega: si llega un conteo suyo es
    una pantalla vieja. Sin esta guardia el reporte se guardaba y reventaba
    después, al confirmar, dejando una fila que alguien tenía que ir a borrar.

    El mensaje no puede nombrar cantidades: lo lee bodega."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    with pytest.raises(ValidationError) as excinfo:
        _contar(db, empresa, asignacion, bodega, buenas=5)

    mensaje = excinfo.value.message
    assert "cerrado" in mensaje
    assert "50" not in mensaje


# --- Lo que ve corte ---


def test_corte_ve_la_diferencia_ya_calculada(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """El momento del producto: las dos cifras una al lado de la otra. Se
    calcula en el servidor para que la cifra que se discute sea una sola."""
    _contar(db, empresa, asignacion, bodega, buenas=48)

    porconfirmar = ConfirmacionCorteService(db).listar_por_confirmar(empresa.id)

    assert len(porconfirmar) == 1
    fila = porconfirmar[0]
    assert fila.cantidad_asignada == 50
    assert fila.cantidad_pendiente == 50
    assert fila.diferencia == -2
    assert fila.contado_por == "Jefa de Bodega"


def test_la_diferencia_positiva_dice_que_llego_de_mas(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Con signo a propósito: "faltan 3" y "sobran 3" son dos conversaciones
    distintas con el taller."""
    _contar(db, empresa, asignacion, bodega, buenas=53)

    assert ConfirmacionCorteService(db).listar_por_confirmar(empresa.id)[0].diferencia == 3


def test_lo_confirmado_ya_no_aparece_por_confirmar(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    assert ConfirmacionCorteService(db).contar_por_confirmar(empresa.id) == 0


# --- Confirmar ---


def test_al_confirmar_nace_la_devolucion_y_se_mueve_el_saldo(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)

    confirmado = ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    assert confirmado.estado == EstadoConteo.CONFIRMADO
    assert confirmado.confirmado_por == "Miriam"
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO
    assert len(fresca.devoluciones) == 1


def test_quien_confirma_queda_escrito(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """El control de cuatro ojos no es una costumbre si se puede comprobar
    después quién contó y quién dio el visto bueno."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    confirmado = ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    assert confirmado.contado_por == "Jefa de Bodega"
    assert confirmado.confirmado_por == "Miriam"
    assert confirmado.confirmado_at is not None


def test_una_entrega_parcial_deja_la_asignacion_abierta(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=30)
    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.estado == EstadoAsignacion.ENTREGADO_PARCIAL


def test_las_danadas_se_vuelven_merma_y_marcan_el_lote(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega: Usuario, corte: Usuario
):
    """La queja de bodega viaja dentro de su conteo: no necesita un trámite
    aparte, y corte la ve en el mismo sitio donde confirma."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=45, danadas=5, nota="Manchadas")

    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    merma = IncidenciaRepository(db).calcular_cantidad_afectada(asignacion.id, empresa.id)
    assert merma == 5
    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA


def test_confirmar_mas_de_lo_que_salio_se_frena_y_explica_con_cifras(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """Este mensaje SÍ nombra las cantidades, y puede: lo lee corte, que tiene
    derecho a verlas. Y dice qué hacer, que es hablar con bodega."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=60)

    with pytest.raises(ValidationError) as excinfo:
        ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    assert "60" in excinfo.value.message and "50" in excinfo.value.message
    assert "bodega" in excinfo.value.message.lower()


def test_confirmar_dos_veces_no_duplica_la_devolucion(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    with pytest.raises(ValidationError):
        ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50


def test_el_doble_clic_con_la_misma_clave_confirma_una_sola_vez(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """El caso más frecuente en planta: la misma persona toca el botón dos
    veces porque la primera no pareció responder."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    servicio = ConfirmacionCorteService(db)

    primero = servicio.confirmar(conteo.id, empresa.id, corte.id, idempotency_key="clic-1")
    segundo = servicio.confirmar(conteo.id, empresa.id, corte.id, idempotency_key="clic-1")

    assert primero.id == segundo.id
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50


def test_dos_tandas_del_mismo_taller_se_acumulan(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """Un taller puede entregar en varias veces; cada tanda es su propio
    conteo y su propia confirmación."""
    servicio = ConfirmacionCorteService(db)
    primero = _contar(db, empresa, asignacion, bodega, buenas=30)
    servicio.confirmar(primero.id, empresa.id, corte.id)
    segundo = _contar(db, empresa, asignacion, bodega, buenas=20)
    servicio.confirmar(segundo.id, empresa.id, corte.id)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO


def test_las_tandas_sin_confirmar_se_leen_como_un_solo_envio(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """El taller trajo las 50 en dos viajes y ninguno está confirmado todavía.

    Mirado reporte por reporte, cada uno parece incompleto: como hasta la
    confirmación no se descuenta nada, los dos se comparan contra el mismo
    pendiente y los dos dicen "faltan". Sumados son la entrega completa, y esa
    es la cifra que corte tiene que ver antes de decidir.
    """
    _contar(db, empresa, asignacion, bodega, buenas=30)
    _contar(db, empresa, asignacion, bodega, buenas=20)

    lista = ConfirmacionCorteService(db).listar_por_confirmar(empresa.id)

    assert [c.diferencia for c in lista] == [-20, -30], "cada tanda suelta parece corta"
    for c in lista:
        assert c.conteos_sin_confirmar == 2
        assert c.contado_sin_confirmar == 50
        assert c.diferencia_del_envio == 0, "juntas sí cuadran con lo que se mandó"


def test_una_sola_tanda_se_lee_igual_que_antes(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """El caso normal no cambia: una entrega, una tarjeta, la misma cifra."""
    _contar(db, empresa, asignacion, bodega, buenas=45, danadas=5)

    [solo] = ConfirmacionCorteService(db).listar_por_confirmar(empresa.id)

    assert solo.conteos_sin_confirmar == 1
    assert solo.contado_sin_confirmar == 50
    assert solo.diferencia_del_envio == solo.diferencia == 0


def test_lo_ya_confirmado_no_suma_al_envio_en_espera(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """Solo cuenta lo que sigue esperando: lo confirmado ya movió el saldo y
    volver a sumarlo haría ver un sobrante que no existe."""
    primero = _contar(db, empresa, asignacion, bodega, buenas=30)
    ConfirmacionCorteService(db).confirmar(primero.id, empresa.id, corte.id)
    _contar(db, empresa, asignacion, bodega, buenas=20)

    [pendiente] = ConfirmacionCorteService(db).listar_por_confirmar(empresa.id)

    assert pendiente.conteos_sin_confirmar == 1
    assert pendiente.contado_sin_confirmar == 20
    assert pendiente.cantidad_pendiente == 20, "las 30 ya confirmadas salieron del saldo"
    assert pendiente.diferencia_del_envio == 0


# --- Corregirse ---


def test_bodega_puede_corregir_mientras_no_este_confirmado(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """La salida cuando la cifra no cuadra: hablan, bodega vuelve a contar y
    arregla su reporte. Por eso no hace falta un estado de 'rechazado'."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    corregido = RecepcionBodegaService(db).corregir(
        conteo.id, empresa.id, ConteoUpdate(cantidad_buena=50)
    )

    assert corregido.cantidad_buena == 50
    assert corregido.estado == EstadoConteo.REPORTADO


def test_despues_de_confirmado_bodega_ya_no_lo_toca(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario, corte: Usuario
):
    """Ya movió el saldo del taller y el estado del lote: deshacer eso no es
    una corrección de captura."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)
    ConfirmacionCorteService(db).confirmar(conteo.id, empresa.id, corte.id)

    with pytest.raises(ValidationError):
        RecepcionBodegaService(db).corregir(
            conteo.id, empresa.id, ConteoUpdate(cantidad_buena=10)
        )
    with pytest.raises(ValidationError):
        RecepcionBodegaService(db).eliminar(conteo.id, empresa.id)


def test_borrar_un_reporte_del_bulto_equivocado(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    RecepcionBodegaService(db).eliminar(conteo.id, empresa.id)

    with pytest.raises(NotFoundError):
        RecepcionBodegaService(db).obtener(conteo.id, empresa.id)


# --- Aislamiento entre empresas ---


def test_una_empresa_no_ve_los_conteos_de_otra(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """La regla de oro del repositorio, comprobada en el camino nuevo."""
    _contar(db, empresa, asignacion, bodega, buenas=48)
    otra = Empresa(nombre="Otra Empresa", activo=True)
    db.add(otra)
    db.commit()

    assert RecepcionBodegaService(db).listar_conteos(otra.id) == []
    assert ConfirmacionCorteService(db).listar_por_confirmar(otra.id) == []
