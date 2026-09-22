# tests/test_recepcion.py
"""
La recepción de bodega: cuenta a ciegas y, si se equivoca, corrige.

Lo que estas pruebas cuidan no es un formulario, es un control. Bodega cuenta
sin saber cuánto se envió; si su cifra no coincide, el sistema NO la rechaza
-- la deja anotada. En lotes viejos se aplica al anotarla; en el flujo de
capas espera a que la proporción esté completa. Corte ya no confirma.
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
    2"; ahora queda anotado. En el lote viejo se aplica al anotarlo."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    assert conteo.cantidad_buena == 48
    assert conteo.estado == EstadoConteo.CONFIRMADO


def test_bodega_puede_reportar_de_mas_sin_que_el_sistema_la_corrija(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Contar 60 de un envío de 50 es justo el caso que hay que poder
    registrar: es un error que alguien tiene que mirar, y el sistema no puede
    taparlo rechazándolo -- ni delatar de paso cuál era el número bueno."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=60)

    assert conteo.cantidad_buena == 60
    assert conteo.estado == EstadoConteo.CONFIRMADO


def test_al_anotar_se_mueve_el_saldo_del_taller(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Corte ya no confirma: al anotar, las buenas entran y el taller baja."""
    _contar(db, empresa, asignacion, bodega, buenas=48)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 48
    assert fresca.estado == EstadoAsignacion.ENTREGADO_PARCIAL


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
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Ese envío ya no sale en la lista de bodega: si llega un conteo suyo es
    una pantalla vieja.

    El mensaje no puede nombrar cantidades: lo lee bodega."""
    _contar(db, empresa, asignacion, bodega, buenas=50)

    with pytest.raises(ValidationError) as excinfo:
        _contar(db, empresa, asignacion, bodega, buenas=5)

    mensaje = excinfo.value.message
    assert "cerrado" in mensaje
    assert "50" not in mensaje


# --- Al anotar se aplica ---


def test_al_anotar_nace_la_devolucion_y_se_mueve_el_saldo(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)

    assert conteo.estado == EstadoConteo.CONFIRMADO
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO
    assert len(fresca.devoluciones) == 1
    assert ConfirmacionCorteService(db).contar_por_confirmar(empresa.id) == 0


def test_una_entrega_parcial_deja_la_asignacion_abierta(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    _contar(db, empresa, asignacion, bodega, buenas=30)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.estado == EstadoAsignacion.ENTREGADO_PARCIAL


def test_las_danadas_se_vuelven_merma_y_marcan_el_lote(
    db: Session, empresa: Empresa, lote: Lote, asignacion, bodega: Usuario
):
    """La queja de bodega viaja dentro de su conteo: no necesita un trámite aparte."""
    _contar(db, empresa, asignacion, bodega, buenas=45, danadas=5, nota="Manchadas")

    merma = IncidenciaRepository(db).calcular_cantidad_afectada(asignacion.id, empresa.id)
    assert merma == 5
    db.refresh(lote)
    assert lote.estado == EstadoLote.EN_REVISION_INCIDENCIA


def test_anotar_de_mas_no_delata_cuanto_salio(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Contar 60 de 50 se guarda: el error no puede enseñarle a bodega el tope."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=60)

    assert conteo.cantidad_buena == 60
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 60
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO


def test_el_doble_clic_con_la_misma_clave_anota_una_sola_vez(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """El caso más frecuente en planta: la misma persona toca el botón dos
    veces porque la primera no pareció responder."""
    servicio = RecepcionBodegaService(db)
    data = ConteoCreate(
        asignacion_id=asignacion.id, cantidad_buena=50, fecha=LLEGADA
    )
    primero = servicio.registrar(empresa.id, data, usuario_id=bodega.id, idempotency_key="clic-1")
    segundo = servicio.registrar(empresa.id, data, usuario_id=bodega.id, idempotency_key="clic-1")

    assert primero.id == segundo.id
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50


def test_dos_tandas_del_mismo_taller_se_acumulan(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Un taller puede entregar en varias veces; cada tanda se aplica al anotarla."""
    _contar(db, empresa, asignacion, bodega, buenas=30)
    _contar(db, empresa, asignacion, bodega, buenas=20)

    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO


# --- Corregirse ---


def test_bodega_puede_corregir_aunque_ya_se_aplico(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    """Si se equivocó, deshace el efecto y vuelve a contar."""
    conteo = _contar(db, empresa, asignacion, bodega, buenas=48)

    corregido = RecepcionBodegaService(db).corregir(
        conteo.id, empresa.id, ConteoUpdate(cantidad_buena=50)
    )

    assert corregido.cantidad_buena == 50
    assert corregido.estado == EstadoConteo.CONFIRMADO
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert fresca.cantidad_devuelta == 50
    assert fresca.estado == EstadoAsignacion.ENTREGADO_COMPLETO


def test_despues_de_aplicado_bodega_sigue_pudiendo_borrar(
    db: Session, empresa: Empresa, asignacion, bodega: Usuario
):
    conteo = _contar(db, empresa, asignacion, bodega, buenas=50)

    RecepcionBodegaService(db).eliminar(conteo.id, empresa.id)

    with pytest.raises(NotFoundError):
        RecepcionBodegaService(db).obtener(conteo.id, empresa.id)
    fresca = AsignacionTallerRepository(db).get_by_id(asignacion.id, empresa.id)
    assert (fresca.cantidad_devuelta or 0) == 0
    assert fresca.estado == EstadoAsignacion.ASIGNADO


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
