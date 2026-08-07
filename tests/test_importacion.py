# tests/test_importacion.py
"""
Carga inicial desde Excel.

Lo grave que puede pasar acá no es que falle: es que FUNCIONE MAL. Crear
ochenta talleres con el teléfono corrido, o duplicar todo el catálogo porque
alguien subió el archivo dos veces, deja al cliente con basura que ya no se
puede borrar (un taller con asignaciones tiene RESTRICT en la FK).

De ahí las dos garantías que se prueban aquí: nada se escribe sin pasar antes
por la previsualización, y si una sola fila está mal no entra ninguna.
"""
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.importacion import HOJA_PRODUCTOS, HOJA_TALLERES, plantilla
from app.models.empresa import Empresa
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.services.importacion_service import ImportacionService


def _archivo(talleres=None, productos=None, titulos_talleres=None, titulos_productos=None):
    """Arma un .xlsx en memoria con las hojas que se le pidan."""
    libro = Workbook()
    libro.remove(libro.active)

    if talleres is not None:
        hoja = libro.create_sheet(HOJA_TALLERES)
        hoja.append(
            titulos_talleres
            or ["Nombre del taller", "Teléfono", "Correo (opcional)", "Dirección (opcional)"]
        )
        for fila in talleres:
            hoja.append(list(fila))

    if productos is not None:
        hoja = libro.create_sheet(HOJA_PRODUCTOS)
        hoja.append(
            titulos_productos
            or ["Nombre del producto", "Referencia", "Precio por unidad (opcional)"]
        )
        for fila in productos:
            hoja.append(list(fila))

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def _contar(db, modelo, empresa_id):
    return db.execute(
        select(func.count()).select_from(modelo).where(modelo.empresa_id == empresa_id)
    ).scalar_one()


def _mensajes(resumen):
    return " | ".join(p.mensaje for p in resumen.problemas)


# --- El camino feliz ---

def test_importa_talleres_y_productos(db: Session, empresa: Empresa):
    contenido = _archivo(
        talleres=[
            ("Confecciones El Sol", "3001234567", "sol@correo.com", "Calle 1"),
            ("Taller Marisol", "3007654321", None, None),
        ],
        productos=[
            ("Chaqueta impermeable", "REF-001", 4500),
            ("Camiseta básica", "REF-002", 1500),
        ],
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)
    assert resumen.se_puede_importar
    assert (resumen.talleres_a_crear, resumen.productos_a_crear) == (2, 2)

    resultado = ImportacionService(db).confirmar(empresa.id, contenido)

    assert (resultado.talleres_creados, resultado.productos_creados) == (2, 2)
    assert _contar(db, Taller, empresa.id) == 2
    assert _contar(db, TipoProducto, empresa.id) == 2


def test_los_precios_quedan_cargados(db: Session, empresa: Empresa):
    ImportacionService(db).confirmar(
        empresa.id, _archivo(productos=[("Chaqueta", "REF-001", 4500)])
    )

    producto = db.execute(select(TipoProducto)).scalars().one()
    assert producto.precio_unitario == Decimal("4500.00")


def test_el_numero_de_taller_lo_pone_la_app(db: Session, empresa: Empresa):
    """El archivo no trae número de taller: es un consecutivo del servidor."""
    ImportacionService(db).confirmar(
        empresa.id,
        _archivo(talleres=[("Taller Uno", "3001111111"), ("Taller Dos", "3002222222")]),
    )

    numeros = sorted(db.execute(select(Taller.numero_taller)).scalars().all())
    assert numeros == ["001", "002"]


def test_el_consecutivo_continua_desde_lo_que_ya_existe(
    db: Session, empresa: Empresa, taller: Taller
):
    """El taller de la fixture ya ocupó el T-001; la importación no lo pisa."""
    taller.numero_taller = "007"
    db.commit()

    ImportacionService(db).confirmar(empresa.id, _archivo(talleres=[("Otro", "3009999999")]))

    nuevo = db.execute(
        select(Taller).where(Taller.nombre == "Otro")
    ).scalars().one()
    assert nuevo.numero_taller == "008"


def test_cada_producto_recibe_su_propio_qr(db: Session, empresa: Empresa):
    ImportacionService(db).confirmar(
        empresa.id,
        _archivo(productos=[("Chaqueta", "REF-001"), ("Camiseta", "REF-002")]),
    )

    productos = db.execute(select(TipoProducto)).scalars().all()
    tokens = {p.qr_code.token for p in productos}
    assert len(tokens) == 2, "dos productos terminaron compartiendo el mismo QR"


# --- La garantía de "todo o nada" ---

def test_una_fila_mala_impide_toda_la_importacion(db: Session, empresa: Empresa):
    """LA garantía del feature. Una carga a medias deja al usuario adivinando
    qué entró y qué no, y los talleres ya creados no se pueden borrar."""
    contenido = _archivo(
        talleres=[
            ("Taller Bueno", "3001234567"),
            ("Taller Malo", "123"),  # teléfono demasiado corto
            ("Otro Bueno", "3007654321"),
        ]
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)
    assert not resumen.se_puede_importar

    with pytest.raises(ValidationError):
        ImportacionService(db).confirmar(empresa.id, contenido)

    assert _contar(db, Taller, empresa.id) == 0, "se crearon talleres pese al error"


def test_la_previsualizacion_no_escribe_nada(db: Session, empresa: Empresa):
    contenido = _archivo(
        talleres=[("Taller Bueno", "3001234567")],
        productos=[("Chaqueta", "REF-001", 4500)],
    )

    ImportacionService(db).previsualizar(empresa.id, contenido)

    assert _contar(db, Taller, empresa.id) == 0
    assert _contar(db, TipoProducto, empresa.id) == 0


def test_dice_en_que_fila_de_excel_esta_el_problema(db: Session, empresa: Empresa):
    """Sin el número de fila, el usuario tiene que buscar el error a ojo en
    un archivo de doscientas líneas."""
    contenido = _archivo(
        talleres=[
            ("Taller Bueno", "3001234567"),
            ("Taller Malo", "123"),
        ]
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    problema = resumen.problemas[0]
    assert problema.fila == 3, "la fila 3 del Excel (título + 2 filas)"
    assert problema.hoja == HOJA_TALLERES


# --- Duplicados: el error que se comete de verdad ---

def test_subir_el_mismo_archivo_dos_veces_no_duplica(db: Session, empresa: Empresa):
    """El error más probable de todos. Sin esta comprobación, el segundo
    intento crea todo otra vez sin que la base se queje: la tabla de talleres
    no tiene UNIQUE sobre el nombre."""
    contenido = _archivo(
        talleres=[("Confecciones El Sol", "3001234567")],
        productos=[("Chaqueta", "REF-001", 4500)],
    )
    ImportacionService(db).confirmar(empresa.id, contenido)

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert not resumen.se_puede_importar
    assert "ya" in _mensajes(resumen).lower()
    with pytest.raises(ValidationError):
        ImportacionService(db).confirmar(empresa.id, contenido)
    assert _contar(db, Taller, empresa.id) == 1


def test_detecta_referencias_repetidas_dentro_del_archivo(db: Session, empresa: Empresa):
    contenido = _archivo(
        productos=[("Chaqueta", "REF-001"), ("Camiseta", "REF-001")]
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert not resumen.se_puede_importar
    assert "repetida" in _mensajes(resumen)


def test_las_referencias_se_comparan_sin_distinguir_mayusculas(
    db: Session, empresa: Empresa
):
    """La base dejaría convivir REF-01 y ref-01, pero para quien las lee son
    la misma y es un error seguro."""
    contenido = _archivo(productos=[("Chaqueta", "REF-001"), ("Camiseta", "ref-001")])

    assert not ImportacionService(db).previsualizar(empresa.id, contenido).se_puede_importar


# --- Tolerancia con el formato ---

def test_acepta_variaciones_en_los_titulos(db: Session, empresa: Empresa):
    """Tolerante con el formato, estricto con la estructura: mayúsculas,
    tildes y sinónimos razonables tienen que funcionar."""
    contenido = _archivo(
        talleres=[("Taller Uno", "3001234567")],
        titulos_talleres=["NOMBRE", "Celular"],
        productos=[("Chaqueta", "REF-001", 1500)],
        titulos_productos=["producto", "Código", "PRECIO"],
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert resumen.se_puede_importar, _mensajes(resumen)
    assert (resumen.talleres_a_crear, resumen.productos_a_crear) == (1, 1)


def test_un_telefono_escrito_como_numero_no_queda_con_decimales(
    db: Session, empresa: Empresa
):
    """Excel guarda 3001234567 como número. Sin cuidado, el teléfono termina
    en la base como '3001234567.0' y el WhatsApp nunca llega."""
    ImportacionService(db).confirmar(empresa.id, _archivo(talleres=[("Taller", 3001234567)]))

    assert db.execute(select(Taller.telefono)).scalar_one() == "3001234567"


def test_las_filas_en_blanco_intercaladas_se_ignoran(db: Session, empresa: Empresa):
    contenido = _archivo(
        talleres=[
            ("Taller Uno", "3001111111"),
            (None, None),
            ("Taller Dos", "3002222222"),
        ]
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert resumen.se_puede_importar, _mensajes(resumen)
    assert resumen.talleres_a_crear == 2


def test_se_puede_subir_solo_una_de_las_dos_hojas(db: Session, empresa: Empresa):
    resultado = ImportacionService(db).confirmar(
        empresa.id, _archivo(talleres=[("Taller Uno", "3001111111")])
    )

    assert (resultado.talleres_creados, resultado.productos_creados) == (1, 0)


# --- Precios: donde adivinar cuesta plata ---

def test_rechaza_un_precio_ambiguo_en_vez_de_adivinar(db: Session, empresa: Empresa):
    """'1.500' puede ser mil quinientos o uno con cinco. Elegir mal significa
    pagarle al taller la milésima parte sin que nadie lo note."""
    contenido = _archivo(productos=[("Chaqueta", "REF-001", "1.500")])

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert not resumen.se_puede_importar
    assert "sin puntos ni comas" in _mensajes(resumen)


def test_el_precio_es_opcional(db: Session, empresa: Empresa):
    ImportacionService(db).confirmar(
        empresa.id, _archivo(productos=[("Chaqueta", "REF-001", None)])
    )

    assert db.execute(select(TipoProducto.precio_unitario)).scalar_one() is None


def test_rechaza_un_precio_negativo(db: Session, empresa: Empresa):
    contenido = _archivo(productos=[("Chaqueta", "REF-001", -100)])

    assert not ImportacionService(db).previsualizar(empresa.id, contenido).se_puede_importar


# --- Archivos que no son lo que deberían ---

def test_un_archivo_que_no_es_excel_da_un_mensaje_claro(db: Session, empresa: Empresa):
    resumen = ImportacionService(db).previsualizar(empresa.id, b"esto no es un excel")

    assert not resumen.se_puede_importar
    assert ".xlsx" in _mensajes(resumen)


def test_un_excel_sin_las_hojas_esperadas(db: Session, empresa: Empresa):
    libro = Workbook()
    libro.active.title = "Hoja1"
    buffer = io.BytesIO()
    libro.save(buffer)

    resumen = ImportacionService(db).previsualizar(empresa.id, buffer.getvalue())

    assert not resumen.se_puede_importar
    assert "plantilla" in _mensajes(resumen)


def test_faltan_columnas_obligatorias(db: Session, empresa: Empresa):
    contenido = _archivo(
        talleres=[("Taller Uno",)], titulos_talleres=["Nombre del taller"]
    )

    resumen = ImportacionService(db).previsualizar(empresa.id, contenido)

    assert not resumen.se_puede_importar
    assert "Teléfono" in _mensajes(resumen)


def test_un_archivo_vacio_lo_dice(db: Session, empresa: Empresa):
    resumen = ImportacionService(db).previsualizar(empresa.id, _archivo(talleres=[]))

    assert not resumen.se_puede_importar
    assert "ninguna fila" in _mensajes(resumen)


# --- La regla de oro ---

def test_la_importacion_no_toca_otra_empresa(db: Session, empresa: Empresa):
    otra = Empresa(nombre="Empresa Vecina", activo=True)
    db.add(otra)
    db.flush()
    vecino = Taller(
        empresa_id=otra.id, nombre="Confecciones El Sol", numero_taller="001",
        telefono="3001112233",
    )
    db.add(vecino)
    db.commit()

    # El mismo nombre existe en la otra empresa, pero no debe estorbar acá.
    resumen = ImportacionService(db).previsualizar(
        empresa.id, _archivo(talleres=[("Confecciones El Sol", "3001234567")])
    )
    assert resumen.se_puede_importar, _mensajes(resumen)

    ImportacionService(db).confirmar(
        empresa.id, _archivo(talleres=[("Confecciones El Sol", "3001234567")])
    )

    assert _contar(db, Taller, empresa.id) == 1
    assert _contar(db, Taller, otra.id) == 1


# --- La plantilla ---

def test_la_plantilla_se_puede_llenar_y_reimportar(db: Session, empresa: Empresa):
    """La prueba de que la plantilla y el lector hablan el mismo idioma: se
    descarga, se llena tal cual, y entra sin problemas."""
    libro = load_workbook(io.BytesIO(plantilla()))
    libro[HOJA_TALLERES].append(["Taller de la Plantilla", "3001234567", None, None])
    libro[HOJA_PRODUCTOS].append(["Producto de la Plantilla", "REF-P1", 2500])
    buffer = io.BytesIO()
    libro.save(buffer)

    resumen = ImportacionService(db).previsualizar(empresa.id, buffer.getvalue())

    assert resumen.se_puede_importar, _mensajes(resumen)
    assert (resumen.talleres_a_crear, resumen.productos_a_crear) == (1, 1)


def test_la_plantilla_no_trae_filas_de_ejemplo(db: Session, empresa: Empresa):
    """Un ejemplo que alguien olvide borrar se importaría como un taller real
    del cliente."""
    resumen = ImportacionService(db).previsualizar(empresa.id, plantilla())

    assert resumen.talleres_a_crear == 0
    assert resumen.productos_a_crear == 0
