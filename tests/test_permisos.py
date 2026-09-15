# tests/test_permisos.py
"""
El mapa de permisos de la API, puesto por puesto.

Es una prueba estructural a propósito: no levanta un servidor ni emite tokens,
recorre las rutas ya registradas y comprueba qué guardia declara cada una. Aun
así falla si alguien quita una guardia sin darse cuenta -- que es exactamente
como se abren estos huecos.

Dos errores son posibles y los dos son caros. Cerrar de más deja a la empresa
sin poder operar: si la de bodega no puede registrar lo que acaba de contar,
todo pasa por el dueño. Abrir de más entrega información o acciones a quien no
le toca. Por eso la tabla de abajo declara el juego EXACTO de puestos de cada
ruta, no un mínimo.

El caso que motivó este archivo: el ranking de talleres y su Excel quedaron
abiertos a cualquier usuario cuando aún mostraban cifras sensibles. Hoy el
ranking es de unidades (sin plata) y lo ven admin+corte, que es quien liquida
talleres; bodega y ventas siguen fuera.
"""
from typing import get_args

from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.core.deps import (
    puede_ver_cantidades,
    require_admin,
    requiere_bodega,
    requiere_corte,
    requiere_operacion,
    requiere_ventas,
)
from app.main import app

# Las guardias que existen, para poder nombrarlas en los mensajes de error.
GUARDIAS = {
    require_admin: "admin",
    requiere_corte: "admin+corte",
    requiere_bodega: "admin+bodega",
    requiere_operacion: "admin+corte+bodega",
    requiere_ventas: "admin+ventas",
    puede_ver_cantidades: "admin+corte+ventas",
}

# Ruta -> guardia exacta. `None` significa "cualquiera que haya iniciado
# sesión": son las pantallas que las cuatro personas necesitan.
MATRIZ = {
    # --- El corte sale y se manda al taller: es el trabajo de CORTE ---
    # El tendido entero: cabecera y líneas de una vez.
    ("/api/v1/cortes", "POST"): requiere_corte,
    # Leerlo lleva cantidades, así que lo ven los tres que pueden verlas.
    ("/api/v1/cortes", "GET"): puede_ver_cantidades,
    ("/api/v1/cortes/{corte_id}", "GET"): puede_ver_cantidades,
    ("/api/v1/colores", "POST"): requiere_corte,
    ("/api/v1/asignaciones", "POST"): requiere_corte,
    ("/api/v1/asignaciones/por-lote/{lote_id}", "GET"): requiere_corte,
    ("/api/v1/asignaciones/{asignacion_id}/reenviar-notificacion", "POST"): requiere_corte,
    ("/api/v1/talleres", "POST"): requiere_corte,
    ("/api/v1/tipos-producto", "POST"): requiere_corte,
    ("/api/v1/talleres/{taller_id}/resumen", "GET"): requiere_corte,
    ("/api/v1/alertas", "GET"): requiere_corte,
    # La vista de escaneo publica cantidad_disponible del lote.
    ("/api/v1/tipos-producto/qr/{token}/lotes-activos", "GET"): requiere_corte,

    # El corte corrige lo que el taller devolvió mal, y levanta la merma: son
    # su lado de la conversación con bodega.
    ("/api/v1/incidencias", "POST"): requiere_corte,
    ("/api/v1/incidencias", "GET"): requiere_corte,
    ("/api/v1/incidencias/{incidencia_id}", "GET"): requiere_corte,
    # Las tres publican cantidad_asignada (IncidenciaOut anida la asignación
    # entera), y el listado además acepta filtrar por lote: sumando se
    # reconstruye el corte completo.
    ("/api/v1/asignaciones", "GET"): requiere_corte,
    ("/api/v1/asignaciones/{asignacion_id}", "GET"): requiere_corte,
    # Corte compara lo que mandó contra lo que bodega contó, y confirma.
    ("/api/v1/recepcion/por-confirmar", "GET"): requiere_corte,
    ("/api/v1/recepcion/conteos/{conteo_id}/comparacion", "GET"): requiere_corte,
    ("/api/v1/recepcion/conteos/{conteo_id}/confirmar", "POST"): requiere_corte,

    # --- Lo que vuelve lo cuenta BODEGA, y solo por estas rutas ---
    #
    # Son las únicas de bodega, y ninguna de sus respuestas declara una
    # cantidad enviada. Eso lo comprueba
    # test_ninguna_respuesta_de_bodega_lleva_cantidades_enviadas, que es la
    # prueba que convierte el conteo a ciegas en una propiedad del código y no
    # en una costumbre.
    ("/api/v1/recepcion/pendientes", "GET"): requiere_bodega,
    ("/api/v1/recepcion/conteos", "POST"): requiere_bodega,
    ("/api/v1/recepcion/conteos", "GET"): requiere_bodega,
    ("/api/v1/recepcion/conteos/{conteo_id}", "GET"): requiere_bodega,
    ("/api/v1/recepcion/conteos/{conteo_id}", "PATCH"): requiere_bodega,
    ("/api/v1/recepcion/conteos/{conteo_id}", "DELETE"): requiere_bodega,

    # --- Lectura compartida: saber de qué taller y de qué producto se habla ---
    ("/api/v1/talleres", "GET"): requiere_operacion,
    ("/api/v1/talleres/{taller_id}", "GET"): requiere_operacion,

    # --- Respuestas con cantidades: BODEGA fuera, cuenta a ciegas ---
    ("/api/v1/lotes", "GET"): puede_ver_cantidades,
    ("/api/v1/lotes/{lote_id}", "GET"): puede_ver_cantidades,
    ("/api/v1/resumen", "GET"): puede_ver_cantidades,
    ("/api/v1/notificaciones", "GET"): puede_ver_cantidades,
    ("/api/v1/notificaciones/leer-todas", "POST"): puede_ver_cantidades,
    ("/api/v1/notificaciones/{aviso_id}/leer", "POST"): puede_ver_cantidades,
    # Saber qué hay listo, y qué viene en camino, es información de
    # producción: lo leen los tres que ven cantidades.
    ("/api/v1/inventario", "GET"): puede_ver_cantidades,
    ("/api/v1/inventario/panorama", "GET"): puede_ver_cantidades,

    # --- El final del recorrido es de VENTAS ---
    #
    # La LISTA de salidas también: ahí está a quién se le mandó, en la nota, y
    # el movimiento comercial no es parte de controlar la producción. Del
    # disponible se deduce que algo salió, y con eso basta para corte.
    ("/api/v1/inventario/ventas", "GET"): requiere_ventas,
    ("/api/v1/inventario/ventas", "POST"): requiere_ventas,
    ("/api/v1/inventario/ventas/{venta_id}", "PATCH"): requiere_ventas,
    ("/api/v1/inventario/ventas/{venta_id}", "DELETE"): requiere_ventas,

    # --- Corregir lo ya capturado es del admin ---
    #
    # La regla venía de cuando el sistema manejaba plata; ese motivo murió con
    # la migración c4a83f1e6db0. El que sobrevive, y que además sobrevive al
    # rediseño: quien captura no corrige su propia captura. Si CORTE pudiera
    # editar la cantidad de un lote después de asignarlo, ajustaría la cifra
    # contra la que se mide a BODEGA y el conteo a dos manos quedaría en nada.
    ("/api/v1/cortes/{corte_id}", "PATCH"): require_admin,
    ("/api/v1/colores/{color_id}", "PATCH"): require_admin,
    ("/api/v1/colores/{color_id}", "DELETE"): require_admin,
    ("/api/v1/lotes/{lote_id}", "PATCH"): require_admin,
    ("/api/v1/lotes/{lote_id}", "DELETE"): require_admin,
    ("/api/v1/lotes/{lote_id}/cerrar-cliente", "POST"): require_admin,
    # Camino viejo de una sola firma: bodega escribía y en el mismo acto se
    # descontaba el saldo. Rechaza el conteo que no cuadra diciendo la cifra
    # exacta, así que en manos de bodega era un oráculo. Queda como salida de
    # emergencia del dueño; el camino normal es /recepcion.
    ("/api/v1/asignaciones/{asignacion_id}/devolucion", "POST"): require_admin,
    ("/api/v1/asignaciones/{asignacion_id}", "PATCH"): require_admin,
    ("/api/v1/asignaciones/{asignacion_id}", "DELETE"): require_admin,
    ("/api/v1/incidencias/{incidencia_id}", "PATCH"): require_admin,
    ("/api/v1/incidencias/{incidencia_id}", "DELETE"): require_admin,
    # Marcar que unas prendas volvieron arregladas es de corte: es quien llama
    # a los talleres por los arreglos. Era de admin por la plata, y la plata
    # se fue en c4a83f1e6db0.
    ("/api/v1/incidencias/{incidencia_id}/convertir-en-devolucion", "POST"): requiere_corte,
    ("/api/v1/talleres/{taller_id}", "PATCH"): require_admin,
    ("/api/v1/talleres/{taller_id}", "DELETE"): require_admin,
    ("/api/v1/tipos-producto/{tipo_producto_id}", "PATCH"): require_admin,
    ("/api/v1/tipos-producto/{tipo_producto_id}", "DELETE"): require_admin,
    ("/api/v1/tipos-producto/{tipo_producto_id}/regenerar-qr", "POST"): require_admin,

    # --- Cosas del dueño: el equipo, la empresa, los proveedores, la carga ---
    ("/api/v1/usuarios", "GET"): require_admin,
    ("/api/v1/usuarios", "POST"): require_admin,
    ("/api/v1/usuarios/{usuario_id}", "GET"): require_admin,
    ("/api/v1/usuarios/{usuario_id}", "PATCH"): require_admin,
    ("/api/v1/usuarios/{usuario_id}", "DELETE"): require_admin,
    ("/api/v1/usuarios/{usuario_id}/anonimizar", "POST"): require_admin,
    ("/api/v1/empresas/actual", "PATCH"): require_admin,
    ("/api/v1/empresas/actual/eliminar", "POST"): require_admin,
    ("/api/v1/empresas/actual/cancelar-eliminacion", "POST"): require_admin,
    ("/api/v1/ranking/talleres", "GET"): requiere_corte,
    ("/api/v1/ranking/talleres.xlsx", "GET"): requiere_corte,
    ("/api/v1/importacion/previsualizar", "POST"): require_admin,
    ("/api/v1/importacion/confirmar", "POST"): require_admin,
    ("/api/v1/importacion/plantilla.xlsx", "GET"): require_admin,

    # --- Las cuatro personas, sin distinción ---
    ("/api/v1/empresas/actual", "GET"): None,
    ("/api/v1/tipos-producto", "GET"): None,
    # El catálogo de colores lo lee todo el mundo: bodega lo necesita para
    # saber cuál de dos bultos del mismo producto tiene delante, y un nombre
    # de color no es una cantidad.
    ("/api/v1/colores", "GET"): None,
    ("/api/v1/tipos-producto/{tipo_producto_id}", "GET"): None,
    ("/api/v1/tipos-producto/qr/{token}", "GET"): None,
    ("/api/v1/usuarios/me/configurar-password", "POST"): None,
    ("/api/v1/usuarios/{usuario_id}/cambiar-password", "POST"): None,
}


def _dependencias(dependant, vistas=None) -> set:
    """Todas las funciones de las que depende un endpoint, incluidas las
    anidadas (las guardias dependen a su vez de get_current_usuario)."""
    vistas = vistas if vistas is not None else set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            vistas.add(sub.call)
        _dependencias(sub, vistas)
    return vistas


def _buscar(path: str, metodo: str) -> APIRoute:
    for ruta in app.routes:
        if isinstance(ruta, APIRoute) and ruta.path == path and metodo in ruta.methods:
            return ruta
    raise AssertionError(f"no existe la ruta {metodo} {path}")


def _guardias_de(ruta: APIRoute) -> set:
    return _dependencias(ruta.dependant) & set(GUARDIAS)


def test_cada_ruta_declara_exactamente_su_guardia():
    for (path, metodo), esperada in MATRIZ.items():
        puestas = _guardias_de(_buscar(path, metodo))
        nombres = sorted(GUARDIAS[g] for g in puestas)

        if esperada is None:
            assert not puestas, (
                f"{metodo} {path} debería estar abierta a los cuatro puestos y "
                f"declara {nombres}"
            )
            continue

        assert puestas == {esperada}, (
            f"{metodo} {path} debería declarar solo '{GUARDIAS[esperada]}' y "
            f"declara {nombres or 'ninguna'}"
        )


def test_ninguna_ruta_declara_dos_guardias():
    """Dos guardias no suman permisos, los restan: FastAPI las evalúa todas, así
    que el resultado es la intersección. `requiere_corte` + `require_admin` deja
    la ruta en solo-admin y el de corte recibe un 403 que nadie quiso."""
    culpables = []
    for ruta in app.routes:
        if isinstance(ruta, APIRoute) and len(_guardias_de(ruta)) > 1:
            nombres = sorted(GUARDIAS[g] for g in _guardias_de(ruta))
            culpables.append(f"{sorted(ruta.methods)} {ruta.path}: {nombres}")

    assert not culpables, "rutas con guardias apiladas: " + "; ".join(culpables)


def test_la_matriz_cubre_todas_las_rutas_de_negocio():
    """Una ruta nueva sin entrada en la matriz es una ruta cuyo permiso nadie
    decidió. Falla aquí para que la decisión se tome en el diff y no en
    producción."""
    publicas = {"/api/v1/auth/", "/health", "/listo"}
    sin_decidir = []
    for ruta in app.routes:
        if not isinstance(ruta, APIRoute):
            continue
        if any(ruta.path.startswith(p) for p in publicas):
            continue
        for metodo in ruta.methods:
            if (ruta.path, metodo) not in MATRIZ:
                sin_decidir.append(f"{metodo} {ruta.path}")

    assert not sin_decidir, (
        "estas rutas no tienen permiso declarado en MATRIZ: "
        + ", ".join(sorted(sin_decidir))
    )


# Campos que dicen, directa o indirectamente, CUÁNTO se le mandó al taller.
# `cantidad_pendiente` y `cantidad_merma` cuentan igual que `cantidad_asignada`:
# quien tiene dos de las tres despeja la tercera de cabeza.
CANTIDADES_ENVIADAS = frozenset(
    {
        "cantidad_asignada",
        "cantidad_pendiente",
        "cantidad_merma",
        "cantidad_devuelta",
        "cantidad_total",
        "cantidad_disponible",
        "diferencia",
    }
)


def _campos_publicados(anotacion, prefijo="", vistos=None) -> set[str]:
    """Todos los campos que una respuesta publica, incluidos los anidados.

    Recursivo a propósito. La fuga más cara que encontramos no era un campo
    suelto sino un schema ENTERO metido dentro de otro: IncidenciaOut anidaba
    AsignacionTallerOut completa, así que publicaba las tres cantidades sin
    que su propia lista de campos las nombrara.
    """
    vistos = vistos if vistos is not None else set()
    campos: set[str] = set()

    for tipo in _desenvolver(anotacion):
        if not (isinstance(tipo, type) and issubclass(tipo, BaseModel)):
            continue
        if tipo in vistos:  # un schema que se anida a sí mismo
            continue
        vistos.add(tipo)
        for nombre, campo in tipo.model_fields.items():
            campos.add(f"{prefijo}{nombre}")
            campos |= _campos_publicados(campo.annotation, f"{prefijo}{nombre}.", vistos)

    return campos


def _desenvolver(anotacion) -> list:
    """Saca el modelo de dentro de list[X], X | None, dict[str, X]..."""
    if anotacion is None:
        return []
    args = get_args(anotacion)
    if not args:
        return [anotacion]
    tipos = []
    for arg in args:
        tipos.extend(_desenvolver(arg))
    return tipos


def test_ninguna_respuesta_de_bodega_lleva_cantidades_enviadas():
    """El requisito del dueño, convertido en una propiedad del código.

    No comprueba que alguien se acuerde de ocultar un campo: comprueba que el
    campo NO EXISTE en ninguna respuesta que bodega pueda pedir. Un schema que
    no declara `cantidad_asignada` no puede filtrarla por descuido, por un `if`
    mal puesto ni por una precarga nueva.

    Recorre las rutas de bodega Y las abiertas a todos, porque bodega también
    alcanza esas. Es estática: corre en milisegundos y cubre schemas que
    todavía no existen.
    """
    culpables = []
    for (path, metodo), guardia in MATRIZ.items():
        if guardia not in (requiere_bodega, None):
            continue
        ruta = _buscar(path, metodo)
        filtrados = _campos_publicados(ruta.response_model) & CANTIDADES_ENVIADAS
        # También los anidados: "asignacion.cantidad_asignada".
        anidados = {
            c for c in _campos_publicados(ruta.response_model)
            if c.rsplit(".", 1)[-1] in CANTIDADES_ENVIADAS
        }
        if filtrados or anidados:
            culpables.append(f"{metodo} {path}: {sorted(filtrados | anidados)}")

    assert not culpables, (
        "estas respuestas alcanzables por bodega publican lo que se envió al "
        "taller, y bodega tiene que contar sin saberlo: " + "; ".join(culpables)
    )


def test_bodega_solo_tiene_las_rutas_de_recepcion():
    """Si bodega gana una ruta fuera de /recepcion, la prueba de arriba puede
    seguir pasando y el conteo a ciegas romperse igual: bastaría con que esa
    ruta nueva publicara la cifra bajo otro nombre. Este cerco es más simple de
    revisar que la lista de campos prohibidos."""
    fuera = [
        f"{metodo} {path}"
        for (path, metodo), guardia in MATRIZ.items()
        if guardia is requiere_bodega and not path.startswith("/api/v1/recepcion/")
    ]

    assert not fuera, (
        "bodega tiene rutas fuera de /recepcion: " + ", ".join(sorted(fuera)) +
        ". Si de verdad las necesita, revisa qué publican antes de agregarlas."
    )
