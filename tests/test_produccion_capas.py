# tests/test_produccion_capas.py
"""El tendido por capas, la asignación por proporciones y el cierre al completar.

El flujo viejo (lineas + color_id + confirmar) se queda para no romper el
front que aún está en producción. Estas pruebas cubren el flujo nuevo: Miriam
escribe colores a mano, manda proporciones enteras, Laura cuenta a ciegas y
la proporción se cierra sola cuando está completa.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.security import hash_password
from app.models.empresa import Empresa
from app.models.enums import EstadoAsignacion, EstadoConteo, RolUsuario
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario
from app.schemas.asignacion_taller import AsignacionTallerCreate
from app.schemas.corte import (
    ColorDeCorteCreate,
    CorteCreate,
    LineaCorteCreate,
    PrendaDeCorteCreate,
)
from app.schemas.inventario import VentaCreate
from app.schemas.recepcion import ConteoCreate
from app.services.asignacion_taller_service import AsignacionTallerService
from app.services.corte_service import CorteService
from app.services.inventario_service import InventarioService
from app.services.recepcion.bodega import RecepcionBodegaService
from app.services.recepcion.corte import ConfirmacionCorteService

HOY = date(2026, 9, 12)
LLEGADA = HOY + timedelta(days=5)


@pytest.fixture
def leguins(lote) -> TipoProducto:
    return lote.tipo_producto


@pytest.fixture
def bodega(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Laura",
        email="laura-bodega@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.BODEGA,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@pytest.fixture
def ventas(db: Session, empresa: Empresa) -> Usuario:
    usuario = Usuario(
        empresa_id=empresa.id,
        nombre="Ventas",
        email="ventas-capas@prueba.com",
        password_hash=hash_password("clave-de-prueba-123"),
        rol=RolUsuario.VENTAS,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def _tendido(db, empresa, leguins, capas=50, negro=20, blanco=30, proporciones=2):
    return CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            capas=capas,
            colores=[
                ColorDeCorteCreate(nombre="Negro", capas=negro),
                ColorDeCorteCreate(nombre="Blanco", capas=blanco),
            ],
            prendas=[PrendaDeCorteCreate(tipo_producto_id=leguins.id, proporciones=proporciones)],
        ),
    )


def _linea(corte, color: str):
    return next(l for l in corte.lineas if l.color == color)


# --- El tendido ---


def test_capas_por_color_por_proporciones_generan_las_unidades(
    db: Session, empresa: Empresa, leguins: TipoProducto
):
    """50 capas, 20 negro + 30 blanco, 2 de leguins → 40 negro y 60 blanco."""
    corte = _tendido(db, empresa, leguins)

    assert corte.capas == 50
    assert [(c.nombre, c.capas) for c in corte.colores] == [("Negro", 20), ("Blanco", 30)]
    negra = _linea(corte, "Negro")
    blanca = _linea(corte, "Blanco")
    assert negra.cantidad == 40
    assert negra.capas_color == 20
    assert negra.proporciones == 2
    assert blanca.cantidad == 60
    assert corte.cantidad_desglosada == 100
    assert corte.diferencia == 0


def test_las_capas_de_los_colores_tienen_que_sumar(
    db: Session, empresa: Empresa, leguins: TipoProducto
):
    with pytest.raises(Exception):
        CorteService(db).crear(
            empresa.id,
            CorteCreate(
                fecha=HOY,
                capas=50,
                colores=[
                    ColorDeCorteCreate(nombre="Negro", capas=20),
                    ColorDeCorteCreate(nombre="Blanco", capas=20),
                ],
                prendas=[PrendaDeCorteCreate(tipo_producto_id=leguins.id, proporciones=2)],
            ),
        )


def test_el_flujo_viejo_de_lineas_sigue_vivo(
    db: Session, empresa: Empresa, leguins: TipoProducto
):
    """El front actual manda lineas. Hasta que se despliegue el nuevo, esto
    no se puede romper."""
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            lineas=[LineaCorteCreate(tipo_producto_id=leguins.id, cantidad=80)],
        ),
    )
    assert corte.capas is None
    assert corte.lineas[0].cantidad == 80
    assert corte.lineas[0].capas_color is None


# --- Asignación ---


def test_se_asignan_proporciones_enteras(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller
):
    corte = _tendido(db, empresa, leguins)
    negra = _linea(corte, "Negro")

    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id,
            taller_id=taller.id,
            proporciones=1,
            fecha_asignacion=HOY,
        ),
    )

    assert envio.cantidad_asignada == 20


def test_no_se_puede_asignar_media_proporcion(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")

    with pytest.raises(ValidationError):
        AsignacionTallerService(db).crear(
            empresa.id,
            AsignacionTallerCreate(
                lote_id=negra.lote_id,
                taller_id=taller.id,
                cantidad_asignada=19,
                fecha_asignacion=HOY,
            ),
        )


def test_una_proporcion_a_cada_taller(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller
):
    otro = Taller(
        empresa_id=empresa.id, nombre="Taller B", numero_taller="T-002", telefono="3000000002"
    )
    db.add(otro)
    db.commit()
    db.refresh(otro)

    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    servicio = AsignacionTallerService(db)
    a = servicio.crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )
    b = servicio.crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=otro.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    assert a.cantidad_asignada == 20
    assert b.cantidad_asignada == 20


def test_la_ficha_es_un_pdf(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    pdf = AsignacionTallerService(db).ficha_pdf(envio.id, empresa.id)

    assert pdf.startswith(b"%PDF-")


# --- Recepción ---


def test_un_conteo_incompleto_no_es_inventario(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=envio.id, cantidad_buena=10, fecha=LLEGADA
        ),
        usuario_id=bodega.id,
    )

    assert conteo.estado == EstadoConteo.REPORTADO
    assert InventarioService(db).resumen(empresa.id).total_disponible == 0
    negra_p = next(
        l for l in InventarioService(db).panorama(empresa.id).lineas if l.color == "Negro"
    )
    assert negra_p.cantidad_en_proceso == 40
    assert negra_p.cantidad_contada == 0


def test_al_completar_la_proporcion_se_cierra_sola(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=envio.id, cantidad_buena=20, fecha=LLEGADA
        ),
        usuario_id=bodega.id,
    )

    assert conteo.estado == EstadoConteo.CONFIRMADO
    assert AsignacionTallerService(db).obtener(envio.id, empresa.id).estado == (
        EstadoAsignacion.ENTREGADO_COMPLETO
    )
    assert InventarioService(db).resumen(empresa.id).total_disponible == 20
    assert ConfirmacionCorteService(db).contar_por_confirmar(empresa.id) == 0


def test_el_arreglo_sigue_pendiente(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=envio.id,
            cantidad_buena=15,
            cantidad_arreglo=5,
            fecha=LLEGADA,
        ),
        usuario_id=bodega.id,
    )

    assert conteo.estado == EstadoConteo.REPORTADO
    assert InventarioService(db).resumen(empresa.id).total_disponible == 0


def test_lo_danado_del_taller_cierra_y_no_entra_al_inventario(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=envio.id,
            cantidad_buena=18,
            cantidad_danada=2,
            fecha=LLEGADA,
        ),
        usuario_id=bodega.id,
    )

    assert InventarioService(db).resumen(empresa.id).total_disponible == 18
    linea = next(
        l for l in InventarioService(db).panorama(empresa.id).lineas if l.color == "Negro"
    )
    assert linea.color == "Negro"
    assert linea.cantidad_perdida == 2
    assert linea.cantidad_contada == 18


def test_la_materia_prima_es_solo_una_nota(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            asignacion_id=envio.id,
            cantidad_buena=20,
            cantidad_danada_materia=3,
            fecha=LLEGADA,
            nota="tela manchada",
        ),
        usuario_id=bodega.id,
    )

    assert conteo.estado == EstadoConteo.CONFIRMADO
    assert conteo.cantidad_danada_materia == 3
    assert InventarioService(db).resumen(empresa.id).total_disponible == 20
    negra_p = next(
        l for l in InventarioService(db).panorama(empresa.id).lineas if l.color == "Negro"
    )
    assert negra_p.cantidad_perdida == 0


def test_bodega_encuentra_el_envio_por_taller_producto_y_color(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega
):
    corte = _tendido(db, empresa, leguins)
    negra = _linea(corte, "Negro")
    AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )

    conteo = RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(
            taller_id=taller.id,
            corte_id=corte.id,
            tipo_producto_id=leguins.id,
            color="negro",
            cantidad_buena=20,
            fecha=LLEGADA,
        ),
        usuario_id=bodega.id,
    )

    assert conteo.estado == EstadoConteo.CONFIRMADO
    assert conteo.color == "Negro"


def test_vender_no_baja_lo_contado_en_bodega(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller, bodega, ventas
):
    negra = _linea(_tendido(db, empresa, leguins), "Negro")
    envio = AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=negra.lote_id, taller_id=taller.id, proporciones=1, fecha_asignacion=HOY
        ),
    )
    RecepcionBodegaService(db).registrar(
        empresa.id,
        ConteoCreate(asignacion_id=envio.id, cantidad_buena=20, fecha=LLEGADA),
        usuario_id=bodega.id,
    )
    InventarioService(db).registrar(
        empresa.id,
        VentaCreate(lote_id=negra.lote_id, cantidad=8, fecha=LLEGADA),
        usuario_id=ventas.id,
    )

    linea = next(
        l for l in InventarioService(db).panorama(empresa.id).lineas if l.color == "Negro"
    )
    assert linea.cantidad_contada == 20
    assert linea.cantidad_disponible == 12
    assert linea.cantidad_vendida == 8
    assert InventarioService(db).resumen(empresa.id).total_disponible == 12


def test_el_panorama_se_filtra_por_taller(
    db: Session, empresa: Empresa, leguins: TipoProducto, taller: Taller
):
    otro = Taller(
        empresa_id=empresa.id, nombre="Taller B", numero_taller="T-002", telefono="3000000002"
    )
    db.add(otro)
    db.commit()
    db.refresh(otro)
    corte = _tendido(db, empresa, leguins)
    AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=_linea(corte, "Negro").lote_id,
            taller_id=taller.id,
            proporciones=1,
            fecha_asignacion=HOY,
        ),
    )
    AsignacionTallerService(db).crear(
        empresa.id,
        AsignacionTallerCreate(
            lote_id=_linea(corte, "Blanco").lote_id,
            taller_id=otro.id,
            proporciones=1,
            fecha_asignacion=HOY,
        ),
    )

    solo_a = InventarioService(db).panorama(empresa.id, taller_id=taller.id)
    assert {l.color for l in solo_a.lineas} == {"Negro"}
