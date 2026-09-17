# tests/test_fugas_de_salida.py
"""
Que ninguna respuesta pueda ganar campos sola.

El producto se vende como control cruzado: bodega cuenta sin ver cuánto se le
envió al taller, y el sistema muestra si concuerda con lo que registró corte.
Ese control se rompe con un solo campo de más en una respuesta -- y la forma
más fácil de que eso pase no es que alguien lo decida, sino que un schema de
salida se arme copiando todas las columnas de la tabla: entonces cada columna
que se agregue al modelo aparece en la API sin que nadie lo note.

Estas dos pruebas cierran ese camino. La primera prohíbe el patrón; la
segunda congela qué columna expone cada schema, para que ampliar la
superficie sea siempre un acto deliberado y visible en el diff.
"""
import io
import tokenize
from pathlib import Path

from app.models.asignacion_taller import AsignacionTaller
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.empresa import Empresa
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.schemas.asignacion_taller import AsignacionTallerOut
from app.schemas.recepcion import ConteoBodegaOut, ConteoPorConfirmarOut
from app.schemas.empresa import EmpresaConEstadisticas
from app.schemas.incidencia import IncidenciaOut
from app.schemas.lote import LoteConDisponibilidad

RAIZ_APP = Path(__file__).resolve().parent.parent / "app"


def _codigo_sin_comentarios(archivo: Path) -> str:
    """El patrón prohibido se nombra en los comentarios que explican por qué
    está prohibido. Se tokeniza para mirar solo el código de verdad y no
    convertir la explicación en un falso positivo."""
    fuente = archivo.read_text(encoding="utf-8")
    piezas = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(fuente).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.NL):
                piezas.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        return fuente
    return " ".join(piezas)


def test_ninguna_respuesta_se_arma_copiando_las_columnas_de_la_tabla():
    """Regresión. Había cinco sitios que hacían

        {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    y se lo pasaban a un schema de salida con **. Funciona, y justamente por
    eso es peligroso: el día que alguien agregue una columna al modelo, esa
    columna sale por la API sin que ninguna prueba falle. Los campos se
    enumeran a mano para que el schema sea la lista blanca.
    """
    culpables = [
        archivo.relative_to(RAIZ_APP.parent).as_posix()
        for archivo in sorted(RAIZ_APP.rglob("*.py"))
        if "__table__" in _codigo_sin_comentarios(archivo)
    ]

    assert not culpables, (
        "estos archivos vuelven a leer las columnas de la tabla para armar una "
        f"respuesta: {culpables}. Enumera los campos del schema a mano."
    )


# Qué columna del modelo expone cada schema de salida, hoy. Si una de estas
# listas cambia, la prueba falla: no para estorbar, sino para que ampliar lo
# que la API publica quede escrito en el diff y alguien lo lea.
SUPERFICIE_PUBLICADA = {
    "AsignacionTallerOut": (
        AsignacionTallerOut,
        AsignacionTaller,
        {
            "id",
            "empresa_id",
            "lote_id",
            "cantidad_asignada",
            "fecha_asignacion",
            "cantidad_devuelta",
            "fecha_devolucion",
            "estado",
            "created_at",
            "updated_at",
        },
    ),
    "IncidenciaOut": (
        IncidenciaOut,
        Incidencia,
        {
            "id",
            "empresa_id",
            "asignacion_id",
            "tipo",
            "cantidad_afectada",
            "descripcion",
            "fecha",
            "created_at",
            "updated_at",
        },
    ),
    "LoteConDisponibilidad": (
        LoteConDisponibilidad,
        Lote,
        {
            "id",
            "empresa_id",
            "cantidad_total",
            "fecha_registro",
            "fecha_entrega_cliente",
            "estado",
            "created_at",
            "updated_at",
        },
    ),
    # Los dos lados de la recepción. La gracia de tenerlos aquí juntos es que
    # la diferencia entre las dos listas se lee de un vistazo: son el mismo
    # hecho contado a dos públicos, y ninguno de los dos publica de más.
    "ConteoBodegaOut": (
        ConteoBodegaOut,
        ConteoRecepcion,
        {
            "id",
            "asignacion_id",
            "cantidad_buena",
            "cantidad_danada",
            "cantidad_danada_materia",
            "cantidad_arreglo",
            "fecha",
            "nota",
            "estado",
            "confirmado_at",
            "created_at",
            "updated_at",
        },
    ),
    "ConteoPorConfirmarOut": (
        ConteoPorConfirmarOut,
        ConteoRecepcion,
        {
            "id",
            "asignacion_id",
            "cantidad_buena",
            "cantidad_danada",
            "cantidad_danada_materia",
            "cantidad_arreglo",
            "fecha",
            "nota",
            "estado",
            "confirmado_at",
            "created_at",
            "updated_at",
        },
    ),
    "EmpresaConEstadisticas": (
        EmpresaConEstadisticas,
        Empresa,
        {
            "id",
            "nombre",
            "activo",
            "dias_alerta_atraso",
            "quincena_dias",
            "eliminacion_solicitada_at",
            "usuario_propietario_id",
            "created_at",
            "updated_at",
        },
    ),
}


def test_la_superficie_publicada_de_cada_schema_esta_congelada():
    for nombre, (schema, modelo, esperado) in SUPERFICIE_PUBLICADA.items():
        columnas = {c.name for c in modelo.__table__.columns}
        expuesto = columnas & set(schema.model_fields)

        assert expuesto == esperado, (
            f"{nombre} cambió qué columnas de {modelo.__tablename__} publica.\n"
            f"  de más: {sorted(expuesto - esperado)}\n"
            f"  de menos: {sorted(esperado - expuesto)}\n"
            "Si es a propósito, actualiza SUPERIFICIE_PUBLICADA en esta prueba."
        )


def test_las_columnas_internas_siguen_sin_publicarse():
    """Los casos concretos que hoy quedan fuera. `ultima_alerta_at` es del
    programador de alertas y los `*_id` de las relaciones ya viajan como
    objeto anidado, así que publicarlos solo agrega ruido."""
    assert "ultima_alerta_at" not in EmpresaConEstadisticas.model_fields
    assert "taller_id" not in AsignacionTallerOut.model_fields
    assert "tipo_producto_id" not in LoteConDisponibilidad.model_fields
    # Quién contó y quién confirmó son ids internos: los dos schemas publican
    # el NOMBRE (y solo el de corte), nunca el id.
    assert "contado_por_id" not in ConteoBodegaOut.model_fields
    assert "confirmado_por_id" not in ConteoPorConfirmarOut.model_fields
    # El puente con la devolución es de auditoría interna, no de la API.
    assert "devolucion_id" not in ConteoPorConfirmarOut.model_fields
