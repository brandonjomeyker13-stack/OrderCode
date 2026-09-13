# tests/test_cortes.py
"""
El corte: un tendido del que salen varios productos en varios colores.

Dos cosas de este archivo valen más que el resto y conviene decirlas arriba.

La primera: un corte se guarda AUNQUE el desglose no sume el total que la
encargada declaró. Ella teclea 500, desglosa 480, y la aplicación lo guarda y
le muestra que faltan 20. Es el mismo criterio que en la recepción -- el
sistema saca el descuadre a la luz y lo resuelve una persona -- y es lo
contrario de lo que haría un formulario que valida.

La segunda: el número del ciclo lo asigna el sistema con la fila de la empresa
bloqueada. Sin eso, dos cortes registrados a la vez se llevan el mismo número
y quedan indistinguibles para siempre.
"""
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.empresa import Empresa
from app.models.lote import Lote
from app.models.tipo_producto import TipoProducto
from app.models.qr_code import QRCode
from app.schemas.corte import ColorCreate, ColorUpdate, CorteCreate, CorteUpdate, LineaCorteCreate
from app.services.color_service import ColorService
from app.services.corte_service import CorteService

HOY = date(2026, 9, 12)


@pytest.fixture
def tipo(db: Session, lote: Lote) -> TipoProducto:
    """El fixture `lote` ya crea un tipo de producto; se reusa."""
    return lote.tipo_producto


@pytest.fixture
def otro_tipo(db: Session, empresa: Empresa) -> TipoProducto:
    qr = QRCode(empresa_id=empresa.id, token="token-dos")
    db.add(qr)
    db.flush()
    tipo = TipoProducto(
        empresa_id=empresa.id, nombre="Camiseta", referencia="REF-002", qr_code_id=qr.id
    )
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return tipo


@pytest.fixture
def negro(db: Session, empresa: Empresa):
    return ColorService(db).crear(empresa.id, ColorCreate(nombre="Negro", hex="#000000"))


@pytest.fixture
def blanco(db: Session, empresa: Empresa):
    return ColorService(db).crear(empresa.id, ColorCreate(nombre="Blanco"))


# --- El catálogo de colores ---


def test_el_mismo_color_escrito_distinto_no_entra_dos_veces(db: Session, empresa: Empresa):
    """Es el punto entero de tener catálogo: sin esto, "Azul rey", "azul rey"
    y "AZUL REY" son tres colores y el inventario los cuenta por separado."""
    servicio = ColorService(db)
    servicio.crear(empresa.id, ColorCreate(nombre="Azul Rey"))

    with pytest.raises(ConflictError):
        servicio.crear(empresa.id, ColorCreate(nombre="azul  rey"))


def test_los_acentos_tampoco_crean_un_color_nuevo(db: Session, empresa: Empresa):
    servicio = ColorService(db)
    servicio.crear(empresa.id, ColorCreate(nombre="Marrón"))

    with pytest.raises(ConflictError):
        servicio.crear(empresa.id, ColorCreate(nombre="marron"))


def test_el_nombre_se_guarda_como_lo_escribieron(db: Session, empresa: Empresa):
    """Se compara normalizado pero se muestra como la persona lo tecleó."""
    color = ColorService(db).crear(empresa.id, ColorCreate(nombre="Azul Rey"))

    assert color.nombre == "Azul Rey"


def test_un_color_sin_usar_se_borra_de_verdad(db: Session, empresa: Empresa):
    """Un dedazo que nunca se usó tiene que poder desaparecer; si no, el
    catálogo se llena de basura que nadie se atreve a tocar."""
    servicio = ColorService(db)
    color = servicio.crear(empresa.id, ColorCreate(nombre="Rjo"))

    servicio.eliminar(color.id, empresa.id)

    assert servicio.listar(empresa.id) == []


def test_un_color_ya_usado_se_desactiva_en_vez_de_borrarse(
    db: Session, empresa: Empresa, tipo: TipoProducto, negro
):
    """Borrarlo dejaría esa línea de corte sin color, y eso es perder historia."""
    CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=100)],
        ),
    )
    servicio = ColorService(db)

    servicio.eliminar(negro.id, empresa.id)

    assert servicio.listar(empresa.id) == []  # ya no se ofrece
    assert len(servicio.listar(empresa.id, incluir_inactivos=True)) == 1  # pero sigue ahí


def test_no_se_puede_usar_un_color_desactivado(
    db: Session, empresa: Empresa, tipo: TipoProducto, negro
):
    ColorService(db).actualizar(negro.id, empresa.id, ColorUpdate(activo=False))

    with pytest.raises(ValidationError):
        CorteService(db).crear(
            empresa.id,
            CorteCreate(
                fecha=HOY,
                lineas=[
                    LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=100)
                ],
            ),
        )


# --- El corte ---


def test_un_corte_con_varios_tipos_y_colores(
    db: Session, empresa: Empresa, tipo: TipoProducto, otro_tipo: TipoProducto, negro, blanco
):
    """Lo que el modelo viejo no sabía decir: de UN tendido salen varias
    combinaciones, y cada una es una línea con su propia cantidad."""
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            cantidad_declarada=300,
            lineas=[
                LineaCorteCreate(
                    tipo_producto_id=tipo.id, color_id=negro.id, cantidad=100, proporciones=2
                ),
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=blanco.id, cantidad=100),
                LineaCorteCreate(tipo_producto_id=otro_tipo.id, color_id=negro.id, cantidad=100),
            ],
        ),
    )

    assert len(corte.lineas) == 3
    assert corte.cantidad_desglosada == 300
    assert corte.diferencia == 0
    negra = next(l for l in corte.lineas if l.color == "Negro" and l.producto == "Producto de Prueba")
    assert negra.proporciones == 2
    assert negra.color_hex == "#000000"


def test_el_desglose_que_no_cuadra_se_guarda_igual(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    """LA prueba de este archivo. Ella declara 500 y desglosa 480: eso no es
    un error de captura que haya que bloquear, es información que alguien
    tiene que ver. Se guarda, y la respuesta trae la diferencia."""
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            cantidad_declarada=500,
            lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=480)],
        ),
    )

    assert corte.cantidad_declarada == 500
    assert corte.cantidad_desglosada == 480
    assert corte.diferencia == 20


def test_sin_total_declarado_no_hay_diferencia_que_mostrar(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    """Declarar el total es opcional: no toda maquila lo hace así."""
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=100)]),
    )

    assert corte.cantidad_declarada is None
    assert corte.diferencia is None


def test_el_color_es_opcional(db: Session, empresa: Empresa, tipo: TipoProducto):
    """No toda maquila trabaja por color, y exigirlo convertiría el catálogo
    en un trámite antes de poder registrar nada."""
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=100)]),
    )

    assert corte.lineas[0].color is None


def test_dos_lineas_del_mismo_tipo_y_color_se_rechazan(
    db: Session, empresa: Empresa, tipo: TipoProducto, negro
):
    """Serían la misma cosa contada dos veces: al mandarlas a talleres nadie
    sabría cuál es cuál, y el inventario mostraría dos filas idénticas."""
    with pytest.raises(ValueError):
        CorteCreate(
            fecha=HOY,
            lineas=[
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=50),
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=50),
            ],
        )


def test_el_mismo_tipo_en_colores_distintos_si_vale(
    db: Session, empresa: Empresa, tipo: TipoProducto, negro, blanco
):
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            lineas=[
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=50),
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=blanco.id, cantidad=50),
            ],
        ),
    )

    assert len(corte.lineas) == 2


def test_un_corte_sin_lineas_no_es_un_corte(db: Session, empresa: Empresa):
    with pytest.raises(ValueError):
        CorteCreate(fecha=HOY, lineas=[])


def test_un_tipo_de_otra_empresa_no_sirve(db: Session, empresa: Empresa):
    with pytest.raises(NotFoundError):
        CorteService(db).crear(
            empresa.id,
            CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=9999, cantidad=10)]),
        )


# --- La numeración cíclica ---


def test_el_primer_corte_de_una_empresa_es_el_uno(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]),
    )

    assert corte.numero == 1
    assert corte.etiqueta == "Corte 01 · 12 sep"


def test_los_numeros_avanzan_de_uno_en_uno(db: Session, empresa: Empresa, tipo: TipoProducto):
    servicio = CorteService(db)
    cuerpo = CorteCreate(
        fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]
    )

    numeros = [servicio.crear(empresa.id, cuerpo).numero for _ in range(3)]

    assert numeros == [1, 2, 3]


def test_al_llegar_al_tope_vuelve_al_uno(db: Session, empresa: Empresa, tipo: TipoProducto):
    """El ciclo es 01-100 y el 100 SÍ se trabaja; después vuelve a empezar.

    Se prueba con un tope de 3 y no de 100 para que corra rápido: el tope es
    configurable por empresa justamente porque no toda maquila cuenta hasta
    100. Y la vuelta se da en OTRA fecha, que es como pasa de verdad: el ciclo
    tarda semanas en dar la vuelta.
    """
    empresa.corte_numero_max = 3
    db.commit()
    servicio = CorteService(db)

    def registrar(dia):
        return servicio.crear(
            empresa.id,
            CorteCreate(
                fecha=date(2026, 9, dia),
                lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)],
            ),
        ).numero

    assert [registrar(dia) for dia in (1, 2, 3, 4)] == [1, 2, 3, 1]


def test_dar_la_vuelta_al_ciclo_el_mismo_dia_se_explica(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    """Caso raro y por eso peligroso: el número vuelve a 1 pero la fecha no
    desempata, así que el corte chocaría con el primero del día. Antes eso
    reventaba con un error de base de datos que la persona no podía resolver;
    ahora se le dice qué hacer."""
    empresa.corte_numero_max = 2
    db.commit()
    servicio = CorteService(db)
    cuerpo = CorteCreate(
        fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]
    )
    servicio.crear(empresa.id, cuerpo)
    servicio.crear(empresa.id, cuerpo)

    with pytest.raises(ValidationError) as excinfo:
        servicio.crear(empresa.id, cuerpo)

    assert "fecha" in excinfo.value.message


def test_dos_cortes_del_mismo_numero_en_fechas_distintas_conviven(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    """Por esto la identidad es NÚMERO + FECHA y no el número solo: el ciclo
    da la vuelta y "el 07" vuelve a aparecer meses después."""
    empresa.corte_numero_max = 1
    db.commit()
    servicio = CorteService(db)

    primero = servicio.crear(
        empresa.id,
        CorteCreate(
            fecha=date(2026, 3, 3), lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]
        ),
    )
    segundo = servicio.crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]),
    )

    assert primero.numero == segundo.numero == 1
    assert primero.etiqueta != segundo.etiqueta


def test_el_ciclo_va_por_empresa(db: Session, empresa: Empresa, tipo: TipoProducto):
    """Regla de oro: el contador de una empresa no toca el de otra."""
    otra = Empresa(nombre="Otra Maquila", activo=True)
    db.add(otra)
    db.commit()
    servicio = CorteService(db)
    servicio.crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]),
    )

    db.refresh(otra)
    assert otra.corte_ultimo_numero == 0


def test_el_doble_clic_no_gasta_dos_numeros(db: Session, empresa: Empresa, tipo: TipoProducto):
    servicio = CorteService(db)
    cuerpo = CorteCreate(
        fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]
    )

    primero = servicio.crear(empresa.id, cuerpo, idempotency_key="clic-1")
    segundo = servicio.crear(empresa.id, cuerpo, idempotency_key="clic-1")

    assert primero.id == segundo.id
    db.refresh(empresa)
    assert empresa.corte_ultimo_numero == 1


# --- Las líneas son lotes de verdad ---


def test_cada_linea_es_un_lote_asignable(
    db: Session, empresa: Empresa, tipo: TipoProducto, negro, blanco
):
    """La línea del corte ES una fila de `lotes`, así que todo lo que ya
    existía -- mandar a taller, devolver, contar -- sigue funcionando sin que
    nadie lo toque."""
    from app.repositories.lote_repository import LoteRepository

    corte = CorteService(db).crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            lineas=[
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=negro.id, cantidad=60),
                LineaCorteCreate(tipo_producto_id=tipo.id, color_id=blanco.id, cantidad=40),
            ],
        ),
    )

    for linea in corte.lineas:
        lote = LoteRepository(db).get_by_id(linea.lote_id, empresa.id)
        assert lote is not None
        assert lote.corte_id == corte.id
        assert lote.cantidad_total == linea.cantidad


def test_corregir_la_cabecera_no_toca_las_lineas(
    db: Session, empresa: Empresa, tipo: TipoProducto
):
    servicio = CorteService(db)
    corte = servicio.crear(
        empresa.id,
        CorteCreate(
            fecha=HOY,
            cantidad_declarada=100,
            lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=100)],
        ),
    )

    corregido = servicio.actualizar(corte.id, empresa.id, CorteUpdate(cantidad_declarada=120))

    assert corregido.cantidad_declarada == 120
    assert corregido.diferencia == 20
    assert len(corregido.lineas) == 1


def test_una_empresa_no_ve_los_cortes_de_otra(db: Session, empresa: Empresa, tipo: TipoProducto):
    CorteService(db).crear(
        empresa.id,
        CorteCreate(fecha=HOY, lineas=[LineaCorteCreate(tipo_producto_id=tipo.id, cantidad=10)]),
    )
    otra = Empresa(nombre="Otra Maquila", activo=True)
    db.add(otra)
    db.commit()

    assert CorteService(db).listar(otra.id) == []
