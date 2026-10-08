# app/core/pdf.py
import io
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Paleta sobria y con buen contraste: la ficha se lee muchas veces desde la
# pantalla de un celular en planta, a veces impresa en blanco y negro.
AZUL = colors.HexColor("#1F3A5F")
GRIS_TEXTO = colors.HexColor("#333333")
GRIS_SUAVE = colors.HexColor("#6B7280")
GRIS_FONDO = colors.HexColor("#F3F4F6")
BORDE = colors.HexColor("#D1D5DB")

_ANCHO_UTIL = letter[0] - 4 * cm

DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _estilo(nombre: str, **kwargs) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 10, "textColor": GRIS_TEXTO, "leading": 14}
    return ParagraphStyle(nombre, **{**base, **kwargs})


def _texto(valor: str) -> str:
    """Escapa el texto que escribió el usuario antes de meterlo en un
    Paragraph. reportlab interpreta un mini-HTML ahí adentro, así que un
    nombre tan normal como "Taller <Sol" o "A & B" o lo desconfigura o
    directamente revienta la generación del PDF -- y con ella, el envío de
    la ficha al taller."""
    return escape(str(valor))


def _fecha_larga(d: date) -> str:
    """En español sin depender del locale del servidor: "Jueves 8 de octubre de 2026"."""
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def _encabezado(empresa_nombre: str) -> Table:
    """Barra superior con el nombre de la empresa y el tipo de documento."""
    izquierda = Paragraph(
        _texto(empresa_nombre),
        _estilo("empresa", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white),
    )
    derecha = Paragraph(
        "FICHA DE ENTREGA",
        _estilo(
            "tipo_doc",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=colors.white,
            alignment=TA_RIGHT,
        ),
    )
    tabla = Table([[izquierda, derecha]], colWidths=[_ANCHO_UTIL * 0.6, _ANCHO_UTIL * 0.4])
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), AZUL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return tabla


def _bloque(etiqueta: str, valor: str, detalle: str | None = None) -> Table:
    contenido = [
        [Paragraph(etiqueta, _estilo("lbl", fontSize=8, textColor=GRIS_SUAVE))],
        [Paragraph(_texto(valor), _estilo("val", fontName="Helvetica-Bold", fontSize=15, leading=19))],
    ]
    if detalle:
        contenido.append(
            [Paragraph(_texto(detalle), _estilo("det", fontSize=10, textColor=GRIS_SUAVE))]
        )
    tabla = Table(contenido, colWidths=[_ANCHO_UTIL / 2 - 6])
    tabla.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return tabla


def _quien_y_cuando(taller_nombre: str, taller_numero: str, fecha: date) -> Table:
    fila = [
        _bloque("ENTREGADO A", taller_nombre, f"Taller N.º {taller_numero}"),
        _bloque("FECHA DE ENTREGA", _fecha_larga(fecha)),
    ]
    tabla = Table([fila], colWidths=[_ANCHO_UTIL / 2, _ANCHO_UTIL / 2])
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tabla


def _que_se_entrega(corte: str | None, prendas: list[tuple[str, list[str]]]) -> Table:
    """Una fila por prenda con sus colores. Sin cantidades: eso lo cuenta bodega."""
    filas = [
        [
            Paragraph("PRENDA", _estilo("h", fontSize=8, textColor=GRIS_SUAVE)),
            Paragraph("COLORES", _estilo("h", fontSize=8, textColor=GRIS_SUAVE)),
        ]
    ]
    for prenda, colores_prenda in prendas:
        filas.append(
            [
                Paragraph(_texto(prenda), _estilo("p", fontName="Helvetica-Bold", fontSize=11)),
                Paragraph(_texto(", ".join(colores_prenda) or "—"), _estilo("c", fontSize=11)),
            ]
        )
    tabla = Table(filas, colWidths=[_ANCHO_UTIL * 0.42, _ANCHO_UTIL * 0.58])
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), GRIS_FONDO),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDE),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDE),
            ]
        )
    )
    titulo = Paragraph(
        f"QUÉ SE ENTREGA{' · ' + _texto(corte).upper() if corte else ''}",
        _estilo("t", fontSize=8, textColor=GRIS_SUAVE),
    )
    envoltura = Table([[titulo], [tabla]], colWidths=[_ANCHO_UTIL])
    envoltura.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return envoltura


def _firmas() -> Table:
    linea = "_" * 34
    celdas = [
        [
            Paragraph(f"{linea}<br/>Entrega", _estilo("f", fontSize=9, textColor=GRIS_SUAVE, alignment=TA_CENTER)),
            Paragraph(f"{linea}<br/>Recibe", _estilo("f", fontSize=9, textColor=GRIS_SUAVE, alignment=TA_CENTER)),
        ]
    ]
    return Table(celdas, colWidths=[_ANCHO_UTIL / 2, _ANCHO_UTIL / 2])


def generar_ficha_tecnica(
    *,
    empresa_nombre: str,
    taller_nombre: str,
    taller_numero: str,
    fecha_asignacion: date,
    asignacion_id: int,
    prendas: list[tuple[str, list[str]]],
    corte: str | None = None,
) -> bytes:
    """
    La hoja que acompaña el bulto: a quién se entrega, cuándo, de qué corte
    y qué prendas en qué colores. No lleva cantidades.

    Pensada para imprimirse en blanco y negro: la jerarquía se apoya en el
    tamaño y el contraste, no en el color.
    """
    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"Ficha de entrega - {taller_nombre}",
        author=empresa_nombre,
    )

    generado = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    pie = Paragraph(
        f"Generado el {generado} · Ref. {asignacion_id}",
        _estilo("pie", fontSize=7, textColor=GRIS_SUAVE, leading=10, alignment=TA_CENTER),
    )

    documento.build(
        [
            _encabezado(empresa_nombre),
            Spacer(1, 22),
            _quien_y_cuando(taller_nombre, taller_numero, fecha_asignacion),
            Spacer(1, 22),
            KeepTogether(_que_se_entrega(corte, prendas)),
            Spacer(1, 60),
            _firmas(),
            Spacer(1, 28),
            pie,
        ]
    )
    return buffer.getvalue()


def prendas_con_colores(lineas: list[tuple[str, str | None]]) -> list[tuple[str, list[str]]]:
    """[(Leguins, Negro), (Leguins, Blanco)] -> [(Leguins, [Negro, Blanco])], en orden."""
    agrupado: dict[str, list[str]] = {}
    for prenda, color in lineas:
        colores_prenda = agrupado.setdefault(prenda, [])
        if color and color not in colores_prenda:
            colores_prenda.append(color)
    return list(agrupado.items())
