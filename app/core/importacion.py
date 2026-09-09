# app/core/importacion.py
"""
Lectura del Excel de carga inicial (talleres y tipos de producto).

Este módulo NO toca la base de datos: solo convierte un archivo en filas
limpias y en una lista de problemas. Las validaciones que necesitan la base
(que una referencia no exista ya) viven en ImportacionService.

Por qué plantilla y no adivinar la estructura: adivinar acierta casi siempre,
y cuando falla no falla con un error -- crea treinta talleres mal en la base
de un cliente. Con plantilla, el problema se ve antes de escribir nada.
Eso sí, es tolerante con el FORMATO: acepta variaciones en los títulos,
ignora columnas de más y no se cae por espacios o mayúsculas.
"""
import io
import unicodedata
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

AZUL = "1F3A5F"
BLANCO = "FFFFFF"

# Tope de tamaño del archivo. openpyxl descomprime en memoria, así que un
# archivo enorme (o un zip malicioso) tumbaría el proceso.
MAX_BYTES = 2 * 1024 * 1024
# Tope de filas por hoja. Una carga inicial real son decenas o cientos de
# filas; miles significa que algo se pegó mal.
MAX_FILAS = 2000
# Cota dura del recorrido: un Excel puede reportar miles de filas "usadas"
# solo porque quedaron con formato, aunque estén vacías.
_MAX_RECORRIDO = 20_000

HOJA_TALLERES = "Talleres"
HOJA_PRODUCTOS = "Productos"


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y sin espacios sobrantes.

    Es lo que permite que "N° Taller", "numero taller" y "NÚMERO TALLER"
    lleguen todos al mismo sitio.
    """
    sin_tildes = "".join(
        letra
        for letra in unicodedata.normalize("NFD", str(texto))
        if unicodedata.category(letra) != "Mn"
    )
    return " ".join(sin_tildes.lower().split())


# Títulos aceptados para cada campo. El primero es el que lleva la plantilla.
_COLUMNAS_TALLER = {
    "nombre": ("Nombre del taller", ("nombre del taller", "nombre", "taller")),
    "telefono": ("Teléfono", ("telefono", "celular", "whatsapp", "numero de telefono")),
    "email": ("Correo (opcional)", ("correo (opcional)", "correo", "email", "e-mail")),
    "direccion": ("Dirección (opcional)", ("direccion (opcional)", "direccion", "ubicacion")),
}
_COLUMNAS_PRODUCTO = {
    "nombre": ("Nombre del producto", ("nombre del producto", "nombre", "producto")),
    "referencia": ("Referencia", ("referencia", "ref", "codigo", "referencia interna")),
}
_OBLIGATORIAS_TALLER = ("nombre", "telefono")
_OBLIGATORIAS_PRODUCTO = ("nombre", "referencia")


@dataclass(frozen=True)
class Problema:
    """`fila` es el número de fila TAL COMO SE VE EN EXCEL, para poder decir
    "arregla la fila 12" y que el usuario la encuentre. None cuando el
    problema es de la hoja entera."""
    hoja: str
    fila: int | None
    mensaje: str


@dataclass(frozen=True)
class FilaTaller:
    fila: int
    nombre: str
    telefono: str
    email: str | None
    direccion: str | None


@dataclass(frozen=True)
class FilaProducto:
    fila: int
    nombre: str
    referencia: str


@dataclass
class ArchivoLeido:
    talleres: list[FilaTaller] = field(default_factory=list)
    productos: list[FilaProducto] = field(default_factory=list)
    problemas: list[Problema] = field(default_factory=list)


def _valor(celda) -> str:
    """El contenido de una celda como texto limpio.

    El caso que importa: los teléfonos y las referencias escritos como número
    llegan como 3001234567 o 3001234567.0. Sin este cuidado, un teléfono
    terminaría guardado como "3001234567.0".
    """
    bruto = celda.value
    if bruto is None:
        return ""
    if isinstance(bruto, float) and bruto.is_integer():
        return str(int(bruto))
    return str(bruto).strip()


def _buscar_hoja(libro, nombre: str):
    objetivo = normalizar(nombre)
    for hoja in libro.worksheets:
        if normalizar(hoja.title) == objetivo:
            return hoja
    return None


def _mapear_columnas(hoja, definicion: dict) -> dict[str, int]:
    """Devuelve {campo: número de columna} leyendo los títulos de la fila 1.

    Una columna que no aparezca simplemente no queda en el mapa; quién decide
    si eso es un problema es cada lector, porque unas columnas son
    obligatorias y otras no.
    """
    encabezados = {}
    for columna in range(1, hoja.max_column + 1):
        titulo = normalizar(_valor(hoja.cell(row=1, column=columna)))
        if titulo:
            encabezados.setdefault(titulo, columna)

    mapa = {}
    for campo, (_, alias) in definicion.items():
        for nombre in alias:
            if nombre in encabezados:
                mapa[campo] = encabezados[nombre]
                break
    return mapa


def _filas_con_datos(hoja, mapa: dict[str, int], nombre_hoja: str, resultado: ArchivoLeido):
    """Recorre la hoja saltando filas vacías. Corta si se pasa del tope."""
    vistas = 0
    tope = min(hoja.max_row, _MAX_RECORRIDO)
    for numero in range(2, tope + 1):
        valores = {campo: _valor(hoja.cell(row=numero, column=col)) for campo, col in mapa.items()}
        if not any(valores.values()):
            continue  # fila en blanco intercalada: se ignora, no es un error

        vistas += 1
        if vistas > MAX_FILAS:
            resultado.problemas.append(
                Problema(
                    nombre_hoja,
                    None,
                    f"La hoja tiene más de {MAX_FILAS} filas con datos. "
                    f"Divide la carga en varios archivos.",
                )
            )
            return
        yield numero, valores


def _leer_talleres(hoja, resultado: ArchivoLeido) -> None:
    mapa = _mapear_columnas(hoja, _COLUMNAS_TALLER)
    obligatorias_faltantes = [c for c in _OBLIGATORIAS_TALLER if c not in mapa]
    if obligatorias_faltantes:
        resultado.problemas.append(
            Problema(
                HOJA_TALLERES,
                None,
                "Faltan columnas obligatorias: "
                + ", ".join(_COLUMNAS_TALLER[c][0] for c in obligatorias_faltantes)
                + ". Descarga la plantilla y no cambies los títulos.",
            )
        )
        return

    for numero, valores in _filas_con_datos(hoja, mapa, HOJA_TALLERES, resultado):
        nombre = valores.get("nombre", "")
        telefono = valores.get("telefono", "")

        if len(nombre) < 2:
            resultado.problemas.append(
                Problema(HOJA_TALLERES, numero, "Falta el nombre del taller.")
            )
            continue
        if len(nombre) > 150:
            resultado.problemas.append(
                Problema(HOJA_TALLERES, numero, "El nombre del taller es demasiado largo.")
            )
            continue
        if not 7 <= len(telefono) <= 20:
            resultado.problemas.append(
                Problema(
                    HOJA_TALLERES,
                    numero,
                    f"El teléfono '{telefono}' no parece válido (entre 7 y 20 caracteres).",
                )
            )
            continue

        correo = valores.get("email") or None
        if correo and "@" not in correo:
            resultado.problemas.append(
                Problema(HOJA_TALLERES, numero, f"El correo '{correo}' no es válido.")
            )
            continue

        resultado.talleres.append(
            FilaTaller(
                fila=numero,
                nombre=nombre,
                telefono=telefono,
                email=correo,
                direccion=(valores.get("direccion") or None),
            )
        )


def _leer_productos(hoja, resultado: ArchivoLeido) -> None:
    mapa = _mapear_columnas(hoja, _COLUMNAS_PRODUCTO)
    obligatorias_faltantes = [c for c in _OBLIGATORIAS_PRODUCTO if c not in mapa]
    if obligatorias_faltantes:
        resultado.problemas.append(
            Problema(
                HOJA_PRODUCTOS,
                None,
                "Faltan columnas obligatorias: "
                + ", ".join(_COLUMNAS_PRODUCTO[c][0] for c in obligatorias_faltantes)
                + ". Descarga la plantilla y no cambies los títulos.",
            )
        )
        return

    for numero, valores in _filas_con_datos(hoja, mapa, HOJA_PRODUCTOS, resultado):
        nombre = valores.get("nombre", "")
        referencia = valores.get("referencia", "")

        if len(nombre) < 2:
            resultado.problemas.append(
                Problema(HOJA_PRODUCTOS, numero, "Falta el nombre del producto.")
            )
            continue
        if not referencia:
            resultado.problemas.append(
                Problema(HOJA_PRODUCTOS, numero, "Falta la referencia.")
            )
            continue
        if len(referencia) > 50:
            resultado.problemas.append(
                Problema(HOJA_PRODUCTOS, numero, "La referencia es demasiado larga.")
            )
            continue

        resultado.productos.append(
            FilaProducto(fila=numero, nombre=nombre, referencia=referencia)
        )


def leer_archivo(contenido: bytes) -> ArchivoLeido:
    """Convierte el .xlsx en filas limpias más la lista de lo que está mal."""
    resultado = ArchivoLeido()

    if len(contenido) > MAX_BYTES:
        resultado.problemas.append(
            Problema("", None, f"El archivo pesa más de {MAX_BYTES // (1024 * 1024)} MB.")
        )
        return resultado

    try:
        # data_only: interesa el resultado de las fórmulas, no la fórmula.
        libro = load_workbook(io.BytesIO(contenido), data_only=True)
    except Exception:
        resultado.problemas.append(
            Problema(
                "",
                None,
                "No se pudo leer el archivo. Debe ser un Excel .xlsx "
                "(si lo tienes en .xls o .csv, guárdalo como .xlsx).",
            )
        )
        return resultado

    hoja_talleres = _buscar_hoja(libro, HOJA_TALLERES)
    hoja_productos = _buscar_hoja(libro, HOJA_PRODUCTOS)

    if hoja_talleres is None and hoja_productos is None:
        resultado.problemas.append(
            Problema(
                "",
                None,
                f"El archivo no tiene ninguna hoja llamada '{HOJA_TALLERES}' ni "
                f"'{HOJA_PRODUCTOS}'. Descarga la plantilla y llénala ahí.",
            )
        )
        return resultado

    if hoja_talleres is not None:
        _leer_talleres(hoja_talleres, resultado)
    if hoja_productos is not None:
        _leer_productos(hoja_productos, resultado)

    return resultado


# --- La plantilla que se descarga ---

_INSTRUCCIONES = (
    ("Cómo cargar tus talleres y productos", True),
    ("", False),
    ("1. Llena la hoja «Talleres» y la hoja «Productos». Puedes usar solo una.", False),
    ("2. No cambies los títulos de las columnas ni el nombre de las hojas.", False),
    ("3. Sube el archivo en la app. Antes de crear nada te va a mostrar qué", False),
    ("   encontró y qué está mal, para que revises.", False),
    ("", False),
    ("Talleres", True),
    ("  • Nombre del taller — obligatorio.", False),
    ("  • Teléfono — obligatorio, entre 7 y 20 caracteres. Ej: 3001234567", False),
    ("  • Correo — opcional. Se usa para mandarle la ficha si WhatsApp falla.", False),
    ("  • Dirección — opcional.", False),
    ("  El número de taller lo asigna la app sola: no lo pongas en el archivo.", False),
    ("", False),
    ("Productos", True),
    ("  • Nombre del producto — obligatorio.", False),
    ("  • Referencia — obligatoria y no se puede repetir. Ej: REF-001", False),
    ("  • Precio por unidad — opcional. Es lo que le pagas al taller por", False),
    ("    cada unidad. Escríbelo solo con números: 1500, no $1.500", False),
    ("", False),
    ("Importante", True),
    ("  Si alguna fila tiene un problema, NO se crea nada: se corrige el", False),
    ("  archivo y se vuelve a subir. Así nunca queda una carga a medias.", False),
    ("", False),
    ("  Si un taller o una referencia ya existe en tu cuenta, se te avisa y", False),
    ("  tienes que quitar esa fila. Evita que se dupliquen por subir dos veces.", False),
)


def _hoja_de_datos(libro: Workbook, titulo: str, definicion: dict, anchos: tuple) -> None:
    hoja = libro.create_sheet(titulo)
    relleno = PatternFill("solid", fgColor=AZUL)
    for indice, campo in enumerate(definicion, start=1):
        celda = hoja.cell(row=1, column=indice)
        celda.value = definicion[campo][0]
        celda.data_type = "s"
        celda.font = Font(bold=True, color=BLANCO)
        celda.fill = relleno
        celda.alignment = Alignment(horizontal="center", vertical="center")
        hoja.column_dimensions[get_column_letter(indice)].width = anchos[indice - 1]
    hoja.freeze_panes = hoja.cell(row=2, column=1)


def plantilla() -> bytes:
    """El archivo que descarga el usuario para llenar.

    Deliberadamente SIN filas de ejemplo en las hojas de datos: un ejemplo que
    alguien olvide borrar se importa como si fuera un taller real. Los
    ejemplos van en la hoja de instrucciones, donde no estorban.
    """
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Instrucciones"
    hoja.column_dimensions["A"].width = 78

    for indice, (texto, es_titulo) in enumerate(_INSTRUCCIONES, start=1):
        celda = hoja.cell(row=indice, column=1)
        celda.value = texto
        celda.data_type = "s"
        if es_titulo:
            celda.font = Font(bold=True, size=12, color=AZUL)

    _hoja_de_datos(libro, HOJA_TALLERES, _COLUMNAS_TALLER, (30, 16, 30, 34))
    _hoja_de_datos(libro, HOJA_PRODUCTOS, _COLUMNAS_PRODUCTO, (34, 18, 24))

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()
