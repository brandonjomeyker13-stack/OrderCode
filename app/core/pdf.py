# app/core/pdf.py
import io
from datetime import date

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


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
    Ficha técnica que se manda por WhatsApp al taller cuando se le asigna un
    lote: qué recibe, cuánto y cuándo (la información que pediste que
    quedara siempre documentada en la entrega).
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 2.5 * cm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "Ficha técnica de asignación")
    y -= 0.9 * cm

    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, empresa_nombre)
    y -= 1.2 * cm

    c.setFont("Helvetica-Bold", 13)
    c.drawString(2 * cm, y, f"Taller: {taller_nombre} (N.º {taller_numero})")
    y -= 1 * cm

    c.setFont("Helvetica", 11)
    filas = [
        ("Producto", tipo_producto_nombre),
        ("Referencia", tipo_producto_referencia),
        ("Cantidad asignada", str(cantidad_asignada)),
        ("Fecha de asignación", fecha_asignacion.strftime("%d/%m/%Y")),
        ("N.º de lote", str(lote_id)),
        ("N.º de asignación", str(asignacion_id)),
    ]
    for etiqueta, valor in filas:
        c.drawString(2 * cm, y, f"{etiqueta}:")
        c.drawString(6 * cm, y, valor)
        y -= 0.8 * cm

    c.showPage()
    c.save()
    return buffer.getvalue()
