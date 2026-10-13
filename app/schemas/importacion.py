# app/schemas/importacion.py
from pydantic import BaseModel


class ProblemaImportacion(BaseModel):
    # Hoja del Excel donde está el problema. Vacío si es del archivo entero.
    hoja: str
    # Número de fila TAL COMO SE VE EN EXCEL, para que el usuario la
    # encuentre sin contar. None cuando el problema es de la hoja completa.
    fila: int | None
    mensaje: str


class ResumenImportacion(BaseModel):
    """Lo que PASARÍA si se confirma. No crea nada.

    Existe para que nadie descubra un archivo mal armado después de haberlo
    metido a la base: revisar 3 filas malas antes es trivial, deshacer 80
    talleres mal creados no lo es.
    """

    talleres_a_crear: int
    productos_a_crear: int
    colores_a_crear: int = 0
    usuarios_a_crear: int = 0
    problemas: list[ProblemaImportacion]
    # False si hay cualquier problema: la importación es todo o nada.
    se_puede_importar: bool


class ResultadoImportacion(BaseModel):
    talleres_creados: int
    productos_creados: int
    colores_creados: int = 0
    usuarios_creados: int = 0
