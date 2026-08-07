# tests/test_ranking.py
"""
El comparativo de talleres por periodo.

Lo que se juega aquí es plata: sobre `unidades_devueltas` del periodo se le
paga a cada taller. Un error de un día en los bordes del corte es un error en
el pago, así que los tests de fechas son los importantes.

Las horas van a mediodía UTC a propósito: a medianoche UTC el día local en
Colombia (UTC-5) todavía es el anterior, y el test estaría comprobando el
huso horario en vez de la lógica.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models.empresa import Empresa
from app.models.enums import EstadoLote, TipoIncidencia
from app.models.lote import Lote
from app.models.qr_code import QRCode
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)
from app.schemas.incidencia import IncidenciaCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.incidencia_service import IncidenciaService
from app.services.ranking_service import RankingService

FEBRERO = (date(2026, 2, 1), date(2026, 2, 28))


@pytest.fixture
def segundo_taller(db: Session, empresa: Empresa) -> Taller:
    taller = Taller(
        empresa_id=empresa.id, nombre="Taller Dos", numero_taller="T-002", telefono="3007654321"
    )
    db.add(taller)
    db.commit()
    db.refresh(taller)
    return taller


def _asignar(db, empresa, lote, taller, cantidad, dia=date(2026, 2, 1)):
    return AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=lote.id,
            taller_id=taller.id,
            cantidad_asignada=cantidad,
            fecha_asignacion=dia,
        ),
    )


def _devolver(db, empresa, asignacion_id, cantidad, dia):
    return AsignacionTallerService(db).registrar_devolucion(
        asignacion_id,
        empresa.id,
        AsignacionTallerRegistrarDevolucion(
            cantidad_devuelta=cantidad,
            fecha_devolucion=datetime(dia.year, dia.month, dia.day, 12, tzinfo=timezone.utc),
        ),
    )


def _merma(db, empresa, asignacion_id, cantidad, dia=date(2026, 2, 3)):
    return IncidenciaService(db).crear(
        empresa.id,
        IncidenciaCreate(
            asignacion_id=asignacion_id,
            tipo=TipoIncidencia.PRODUCTO_DANADO,
            cantidad_afectada=cantidad,
            descripcion="daño",
            fecha=dia,
        ),
    )


def _fila(ranking, taller_id):
    return next(f for f in ranking.talleres if f.taller_id == taller_id)


# --- Las cifras ---

def test_las_cifras_del_periodo_cuadran(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """200 asignadas, 20 dañadas, 50 entregadas -> 130 siguen en el taller."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _merma(db, empresa, asignacion.id, 20)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 5))

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.unidades_asignadas == 200
    assert fila.unidades_devueltas == 50
    assert fila.unidades_merma == 20
    assert fila.entregas == 1
    assert fila.unidades_pendientes == 130
    # Del 1 al 5 de febrero.
    assert fila.dias_promedio_entrega == 4.0


def test_la_tasa_de_merma_se_calcula_sobre_lo_terminado(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """De 100 unidades que el taller cerró, 20 salieron dañadas -> 20%.

    Si el denominador fuera lo asignado (200), daría 10% y premiaría al taller
    solo por no haber terminado todavía.
    """
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _merma(db, empresa, asignacion.id, 20)
    _devolver(db, empresa, asignacion.id, 80, date(2026, 2, 5))

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.tasa_merma == 20.0


def test_sin_movimiento_la_tasa_de_merma_es_cero_y_no_revienta(
    db: Session, empresa: Empresa, taller: Taller
):
    """El caso de la división por cero: un taller que no cerró nada."""
    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.tasa_merma == 0.0
    # None y no 0.0: un cero se leería como "entrega el mismo día".
    assert fila.dias_promedio_entrega is None


def test_el_promedio_de_dias_usa_todas_las_entregas(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Entregó a los 2 días y a los 6 -> promedio 4."""
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 40, date(2026, 2, 3))
    _devolver(db, empresa, asignacion.id, 60, date(2026, 2, 7))

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.entregas == 2
    assert fila.dias_promedio_entrega == 4.0


# --- El periodo: donde se pagan los errores ---

def test_una_entrega_fuera_del_periodo_no_cuenta(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """La razón de ser del filtro: lo entregado en febrero no se le puede
    volver a pagar en el corte de marzo."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 5))

    marzo = RankingService(db).talleres(empresa.id, date(2026, 3, 1), date(2026, 3, 31))

    assert _fila(marzo, taller.id).unidades_devueltas == 0
    assert marzo.total_unidades_devueltas == 0


def test_solo_cuenta_lo_entregado_dentro_del_corte(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Dos tandas, una en cada quincena. El corte de la primera ve solo la
    suya -- no el acumulado de la asignación, que es el error clásico."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 10))
    _devolver(db, empresa, asignacion.id, 70, date(2026, 2, 20))

    primera = RankingService(db).talleres(empresa.id, date(2026, 2, 1), date(2026, 2, 15))
    segunda = RankingService(db).talleres(empresa.id, date(2026, 2, 16), date(2026, 2, 28))

    assert _fila(primera, taller.id).unidades_devueltas == 50
    assert _fila(segunda, taller.id).unidades_devueltas == 70


def test_el_periodo_incluye_los_dos_extremos(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Pedir del 5 al 5 incluye lo entregado el día 5. Si el último día
    quedara fuera, cada corte le robaría un día de trabajo al taller."""
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 30, date(2026, 2, 5))

    ranking = RankingService(db).talleres(empresa.id, date(2026, 2, 5), date(2026, 2, 5))

    assert _fila(ranking, taller.id).unidades_devueltas == 30


def test_lo_pendiente_no_se_recorta_por_periodo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """`unidades_pendientes` es un saldo de hoy, no del corte: el taller sigue
    teniendo esas unidades aunque se consulte otro mes."""
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 5))

    marzo = RankingService(db).talleres(empresa.id, date(2026, 3, 1), date(2026, 3, 31))

    assert _fila(marzo, taller.id).unidades_pendientes == 150


def test_desde_posterior_a_hasta_se_rechaza(db: Session, empresa: Empresa):
    with pytest.raises(ValidationError):
        RankingService(db).talleres(empresa.id, date(2026, 3, 1), date(2026, 2, 1))


# --- El orden, que es lo que lo hace un "ranking" ---

def test_ordena_por_unidades_entregadas(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    primera = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, primera.id, 30, date(2026, 2, 5))
    segunda = _asignar(db, empresa, lote, segundo_taller, 150)
    _devolver(db, empresa, segunda.id, 120, date(2026, 2, 5))

    ranking = RankingService(db).talleres(empresa.id, *FEBRERO)

    assert [f.taller_id for f in ranking.talleres] == [segundo_taller.id, taller.id]
    assert ranking.total_unidades_devueltas == 150


# --- Qué talleres aparecen ---

def test_un_taller_desactivado_sin_movimiento_no_ensucia_la_tabla(
    db: Session, empresa: Empresa, taller: Taller, segundo_taller: Taller
):
    segundo_taller.activo = False
    db.commit()

    ranking = RankingService(db).talleres(empresa.id, *FEBRERO)

    assert [f.taller_id for f in ranking.talleres] == [taller.id]


def test_un_taller_desactivado_con_movimiento_si_aparece(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller, segundo_taller: Taller
):
    """Se le puede deber plata del corte anterior a haberlo desactivado."""
    asignacion = _asignar(db, empresa, lote, segundo_taller, 100)
    _devolver(db, empresa, asignacion.id, 100, date(2026, 2, 5))
    segundo_taller.activo = False
    db.commit()

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), segundo_taller.id)

    assert fila.unidades_devueltas == 100
    assert fila.activo is False


# --- La regla de oro ---

def test_el_ranking_no_mezcla_datos_de_otra_empresa(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 40, date(2026, 2, 5))

    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.flush()
    qr = QRCode(empresa_id=otra.id, token="qr-vecino")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=otra.id, nombre="Producto Vecino", referencia="REF-V", qr_code_id=qr.id
    )
    db.add(tipo)
    db.flush()
    lote_vecino = Lote(
        empresa_id=otra.id,
        tipo_producto_id=tipo.id,
        cantidad_total=999,
        fecha_registro=date(2026, 1, 1),
        estado=EstadoLote.PENDIENTE_ASIGNACION,
    )
    taller_vecino = Taller(
        empresa_id=otra.id, nombre="Taller Vecino", numero_taller="TV-1", telefono="3001112233"
    )
    db.add_all([lote_vecino, taller_vecino])
    db.commit()
    ajena = _asignar(db, otra, lote_vecino, taller_vecino, 900)
    _devolver(db, otra, ajena.id, 800, date(2026, 2, 5))

    ranking = RankingService(db).talleres(empresa.id, *FEBRERO)

    assert [f.taller_id for f in ranking.talleres] == [taller.id]
    assert ranking.total_unidades_devueltas == 40, "se filtraron entregas de otra empresa"


# --- La plata ---

def _poner_precio(db, lote, precio):
    lote.tipo_producto.precio_unitario = Decimal(precio)
    db.commit()


def test_el_monto_a_pagar_sale_de_lo_entregado_en_el_periodo(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """80 unidades a $1.500 = $120.000. Se paga lo ENTREGADO, no lo asignado:
    el taller todavía tiene 120 unidades encima y esas no se le pagan aún."""
    _poner_precio(db, lote, "1500")
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 80, date(2026, 2, 5))

    ranking = RankingService(db).talleres(empresa.id, *FEBRERO)

    assert _fila(ranking, taller.id).monto_a_pagar == Decimal("120000")
    assert ranking.total_a_pagar == Decimal("120000")


def test_la_merma_no_se_paga(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """Las unidades dañadas no entran al monto: no son producto entregado."""
    _poner_precio(db, lote, "1000")
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _merma(db, empresa, asignacion.id, 30)
    _devolver(db, empresa, asignacion.id, 70, date(2026, 2, 5))

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.monto_a_pagar == Decimal("70000")


def test_subir_el_precio_no_reescribe_lo_ya_asignado(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """EL test de esta funcionalidad.

    El precio se congela en la asignación. Si se leyera el precio actual del
    producto, subir la tarifa en marzo cambiaría solo el monto del corte de
    febrero que ya se pagó -- y nadie se enteraría hasta el descuadre.
    """
    _poner_precio(db, lote, "1000")
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 5))

    _poner_precio(db, lote, "2000")  # la mano de obra subió

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    assert fila.monto_a_pagar == Decimal("50000"), "el cambio de precio alteró un corte pasado"


def test_el_precio_nuevo_si_aplica_a_las_asignaciones_siguientes(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """La otra mitad: lo que sale después del aumento sí se paga al precio
    nuevo. Si no, congelar el precio sería simplemente ignorarlo."""
    _poner_precio(db, lote, "1000")
    vieja = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, vieja.id, 100, date(2026, 2, 5))

    _poner_precio(db, lote, "2000")
    nueva = _asignar(db, empresa, lote, taller, 100, dia=date(2026, 2, 10))
    _devolver(db, empresa, nueva.id, 100, date(2026, 2, 15))

    fila = _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id)

    # 100 x 1000 + 100 x 2000
    assert fila.monto_a_pagar == Decimal("300000")


def test_las_unidades_sin_precio_se_reportan_aparte(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    """Sin esto, "faltó cargar el precio" y "trabajó poco" se ven idénticos:
    un monto bajo. El usuario tiene que poder distinguirlos."""
    asignacion = _asignar(db, empresa, lote, taller, 100)  # producto sin precio
    _devolver(db, empresa, asignacion.id, 60, date(2026, 2, 5))

    ranking = RankingService(db).talleres(empresa.id, *FEBRERO)
    fila = _fila(ranking, taller.id)

    assert fila.monto_a_pagar == Decimal("0")
    assert fila.unidades_sin_tarifa == 60
    assert ranking.total_unidades_sin_tarifa == 60


def test_un_producto_con_precio_no_deja_unidades_sin_tarifa(
    db: Session, empresa: Empresa, lote: Lote, taller: Taller
):
    _poner_precio(db, lote, "1500")
    asignacion = _asignar(db, empresa, lote, taller, 100)
    _devolver(db, empresa, asignacion.id, 60, date(2026, 2, 5))

    assert _fila(RankingService(db).talleres(empresa.id, *FEBRERO), taller.id).unidades_sin_tarifa == 0


def test_el_monto_respeta_el_corte(db: Session, empresa: Empresa, lote: Lote, taller: Taller):
    """Lo pagado en la primera quincena no se vuelve a pagar en la segunda."""
    _poner_precio(db, lote, "1000")
    asignacion = _asignar(db, empresa, lote, taller, 200)
    _devolver(db, empresa, asignacion.id, 50, date(2026, 2, 10))
    _devolver(db, empresa, asignacion.id, 70, date(2026, 2, 20))

    primera = RankingService(db).talleres(empresa.id, date(2026, 2, 1), date(2026, 2, 15))
    segunda = RankingService(db).talleres(empresa.id, date(2026, 2, 16), date(2026, 2, 28))

    assert primera.total_a_pagar == Decimal("50000")
    assert segunda.total_a_pagar == Decimal("70000")


# --- Rendimiento ---

def test_no_dispara_una_consulta_por_taller(db: Session, empresa: Empresa, lote: Lote):
    """El ranking cruza cuatro tablas: hecho ingenuamente, sería una consulta
    por taller y se caería con el primer cliente que tenga treinta."""
    for numero in range(10):
        taller = Taller(
            empresa_id=empresa.id,
            nombre=f"Taller {numero}",
            numero_taller=f"T-{numero:03d}",
            telefono="3001234567",
        )
        db.add(taller)
        db.flush()
        asignacion = _asignar(db, empresa, lote, taller, 10)
        _devolver(db, empresa, asignacion.id, 5, date(2026, 2, 5))
    db.commit()
    db.expire_all()

    conteo = {"n": 0}
    motor = db.get_bind()

    @event.listens_for(motor, "before_cursor_execute")
    def contar(conn, cursor, stmt, params, ctx, many):
        conteo["n"] += 1

    try:
        ranking = RankingService(db).talleres(empresa.id, *FEBRERO)
    finally:
        event.remove(motor, "before_cursor_execute", contar)

    assert len(ranking.talleres) == 10
    assert conteo["n"] < 10, f"parece un N+1: {conteo['n']} consultas para 10 talleres"
