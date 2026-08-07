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


def _encabezado(empresa_nombre: str) -> Table:
    """Barra superior con el nombre de la empresa y el tipo de documento."""
    izquierda = Paragraph(
        _texto(empresa_nombre),
        _estilo("empresa", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white),
    )
    derecha = Paragraph(
        "FICHA TÉCNICA",
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


def _bloque_destinatario(taller_nombre: str, taller_numero: str) -> Table:
    contenido = [
        [Paragraph("ENTREGADO A", _estilo("lbl", fontSize=8, textColor=GRIS_SUAVE))],
        [
            Paragraph(
                _texto(taller_nombre), _estilo("taller", fontName="Helvetica-Bold", fontSize=15, leading=19)
            )
        ],
        [Paragraph(f"Taller N.º {_texto(taller_numero)}", _estilo("num", fontSize=10, textColor=GRIS_SUAVE))],
    ]
    tabla = Table(contenido, colWidths=[_ANCHO_UTIL])
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


def _destacado_cantidad(cantidad: int, fecha_asignacion: date) -> Table:
    """La cantidad es EL dato de esta ficha -- si el taller solo mira una cosa,
    tiene que ser cuántas unidades recibió. Por eso va en grande y aislada."""
    celda_cantidad = [
        Paragraph("CANTIDAD ASIGNADA", _estilo("lbl_cant", fontSize=8, textColor=GRIS_SUAVE, alignment=TA_CENTER)),
        Paragraph(
            f"{cantidad:,}".replace(",", "."),
            _estilo("cant", fontName="Helvetica-Bold", fontSize=30, textColor=AZUL, leading=34, alignment=TA_CENTER),
        ),
        Paragraph("unidades", _estilo("uds", fontSize=9, textColor=GRIS_SUAVE, alignment=TA_CENTER)),
    ]
    celda_fecha = [
        Paragraph("FECHA DE ENTREGA", _estilo("lbl_fecha", fontSize=8, textColor=GRIS_SUAVE, alignment=TA_CENTER)),
        Paragraph(
            fecha_asignacion.strftime("%d/%m/%Y"),
            _estilo("fecha", fontName="Helvetica-Bold", fontSize=18, leading=26, alignment=TA_CENTER),
        ),
        Paragraph(
            fecha_asignacion.strftime("%A").capitalize(),
            _estilo("dia", fontSize=9, textColor=GRIS_SUAVE, alignment=TA_CENTER),
        ),
    ]
    interna_izq = Table([[p] for p in celda_cantidad], colWidths=[_ANCHO_UTIL * 0.5 - 1])
    interna_der = Table([[p] for p in celda_fecha], colWidths=[_ANCHO_UTIL * 0.5 - 1])
    for t in (interna_izq, interna_der):
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))

    tabla = Table([[interna_izq, interna_der]], colWidths=[_ANCHO_UTIL * 0.5, _ANCHO_UTIL * 0.5])
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GRIS_FONDO),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDE),
                ("LINEAFTER", (0, 0), (0, 0), 0.75, BORDE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    return tabla


def _tabla_detalle(filas: list[tuple[str, str]]) -> Table:
    contenido = [
        [
            Paragraph(_texto(etiqueta), _estilo("k", fontSize=9, textColor=GRIS_SUAVE)),
            Paragraph(_texto(valor), _estilo("v", fontName="Helvetica-Bold", fontSize=10)),
        ]
        for etiqueta, valor in filas
    ]
    tabla = Table(contenido, colWidths=[_ANCHO_UTIL * 0.4, _ANCHO_UTIL * 0.6])
    tabla.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                # Franjas alternas: ayudan a no perder el renglón al leer en
                # una pantalla pequeña.
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, GRIS_FONDO]),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDE),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, BORDE),
            ]
        )
    )
    return tabla


def generar_ficha_tecnica(
    *,
    empresa_nombre: str,
    taller_nombre: str,
    taller_numero: str,
    tipo_producto_nombre: str,
    tipo_producto_referencia: str,
    cantidad_asignada: int,
    fecha_asignacion: date,
    lote_id: int,
    asignacion_id: int,
) -> bytes:
    """
    Ficha técnica que se le manda al taller cuando se le asigna un lote: qué
    recibe, cuánto y cuándo.

    Pensada para leerse en el celular en planta y para imprimirse en blanco y
    negro: la jerarquía se apoya en el tamaño y el contraste, no en el color.
    """
    buffer = io.BytesIO()
    documento = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"Ficha técnica - Asignación {asignacion_id}",
        author=empresa_nombre,
    )

    detalle = [
        ("Producto", tipo_producto_nombre),
        ("Referencia", tipo_producto_referencia),
        ("N.º de lote", str(lote_id)),
        ("N.º de asignación", str(asignacion_id)),
    ]

    generado = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    pie = Paragraph(
        f"Documento generado automáticamente el {generado}.<br/>"
        "Consérvalo como comprobante de lo recibido. Ante cualquier diferencia "
        f"en la cantidad, repórtala a {_texto(empresa_nombre)} antes de comenzar la producción.",
        _estilo("pie", fontSize=8, textColor=GRIS_SUAVE, leading=11, alignment=TA_CENTER),
    )

    documento.build(
        [
            _encabezado(empresa_nombre),
            Spacer(1, 22),
            _bloque_destinatario(taller_nombre, taller_numero),
            Spacer(1, 16),
            # KeepTogether evita que el dato principal quede huérfano si algún
            # día la ficha crece y se parte en dos páginas.
            KeepTogether(_destacado_cantidad(cantidad_asignada, fecha_asignacion)),
            Spacer(1, 18),
            _tabla_detalle(detalle),
            Spacer(1, 28),
            pie,
        ]
    )
    return buffer.getvalue()
