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
abiertos a cualquier usuario cuando se les agregó una cifra sensible, así que
un operario podía ver el desempeño comparado de todos los talleres.
"""
from fastapi.routing import APIRoute

from app.core.deps import (
    puede_ver_cantidades,
    require_admin,
    requiere_bodega,
    requiere_corte,
    requiere_operacion,
)
from app.main import app

# Las guardias que existen, para poder nombrarlas en los mensajes de error.
GUARDIAS = {
    require_admin: "admin",
    requiere_corte: "admin+corte",
    requiere_bodega: "admin+bodega",
    requiere_operacion: "admin+corte+bodega",
    puede_ver_cantidades: "admin+corte+ventas",
}

# Ruta -> guardia exacta. `None` significa "cualquiera que haya iniciado
# sesión": son las pantallas que las cuatro personas necesitan.
MATRIZ = {
    # --- El corte sale y se manda al taller: es el trabajo de CORTE ---
    ("/api/v1/lotes", "POST"): requiere_corte,
    ("/api/v1/asignaciones", "POST"): requiere_corte,
    ("/api/v1/asignaciones/por-lote/{lote_id}", "GET"): requiere_corte,
    ("/api/v1/asignaciones/{asignacion_id}/reenviar-notificacion", "POST"): requiere_corte,
    ("/api/v1/talleres", "POST"): requiere_corte,
    ("/api/v1/tipos-producto", "POST"): requiere_corte,
    ("/api/v1/talleres/{taller_id}/resumen", "GET"): requiere_corte,
    ("/api/v1/alertas", "GET"): requiere_corte,
    # La vista de escaneo publica cantidad_disponible del lote.
    ("/api/v1/tipos-producto/qr/{token}/lotes-activos", "GET"): requiere_corte,

    # --- Lo que vuelve lo cuenta BODEGA, y CORTE queda fuera a propósito ---
    ("/api/v1/asignaciones/{asignacion_id}/devolucion", "POST"): requiere_bodega,
    ("/api/v1/incidencias", "POST"): requiere_bodega,

    # --- Lectura compartida: saber de qué taller y de qué producto se habla ---
    ("/api/v1/talleres", "GET"): requiere_operacion,
    ("/api/v1/talleres/{taller_id}", "GET"): requiere_operacion,
    ("/api/v1/asignaciones", "GET"): requiere_operacion,
    ("/api/v1/asignaciones/{asignacion_id}", "GET"): requiere_operacion,
    ("/api/v1/incidencias", "GET"): requiere_operacion,
    ("/api/v1/incidencias/{incidencia_id}", "GET"): requiere_operacion,

    # --- Respuestas con cantidades: BODEGA fuera, cuenta a ciegas ---
    ("/api/v1/lotes", "GET"): puede_ver_cantidades,
    ("/api/v1/lotes/{lote_id}", "GET"): puede_ver_cantidades,
    ("/api/v1/resumen", "GET"): puede_ver_cantidades,
    ("/api/v1/notificaciones", "GET"): puede_ver_cantidades,
    ("/api/v1/notificaciones/leer-todas", "POST"): puede_ver_cantidades,
    ("/api/v1/notificaciones/{aviso_id}/leer", "POST"): puede_ver_cantidades,

    # --- Corregir lo ya capturado es del admin ---
    #
    # La regla venía de cuando el sistema manejaba plata; ese motivo murió con
    # la migración c4a83f1e6db0. El que sobrevive, y que además sobrevive al
    # rediseño: quien captura no corrige su propia captura. Si CORTE pudiera
    # editar la cantidad de un lote después de asignarlo, ajustaría la cifra
    # contra la que se mide a BODEGA y el conteo a dos manos quedaría en nada.
    ("/api/v1/lotes/{lote_id}", "PATCH"): require_admin,
    ("/api/v1/lotes/{lote_id}", "DELETE"): require_admin,
    ("/api/v1/lotes/{lote_id}/cerrar-cliente", "POST"): require_admin,
    ("/api/v1/asignaciones/{asignacion_id}", "PATCH"): require_admin,
    ("/api/v1/asignaciones/{asignacion_id}", "DELETE"): require_admin,
    ("/api/v1/incidencias/{incidencia_id}", "PATCH"): require_admin,
    ("/api/v1/incidencias/{incidencia_id}", "DELETE"): require_admin,
    ("/api/v1/incidencias/{incidencia_id}/convertir-en-devolucion", "POST"): require_admin,
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
    ("/api/v1/ranking/talleres", "GET"): require_admin,
    ("/api/v1/ranking/talleres.xlsx", "GET"): require_admin,
    ("/api/v1/importacion/previsualizar", "POST"): require_admin,
    ("/api/v1/importacion/confirmar", "POST"): require_admin,
    ("/api/v1/importacion/plantilla.xlsx", "GET"): require_admin,

    # --- Las cuatro personas, sin distinción ---
    ("/api/v1/empresas/actual", "GET"): None,
    ("/api/v1/tipos-producto", "GET"): None,
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


def test_bodega_no_alcanza_ninguna_ruta_con_cantidades():
    """El requisito del dueño, escrito como prueba: bodega cuenta a ciegas.

    Ojo con lo que esta prueba SÍ y NO garantiza. Garantiza que bodega no puede
    LLAMAR a las rutas cuya respuesta lleva cantidades. NO garantiza el conteo a
    ciegas completo: las rutas que bodega sí necesita (GET /asignaciones, para
    saber a qué taller le anota) todavía devuelven cantidad_asignada, y
    POST /devolucion rechaza un conteo que no cuadre diciendo la cifra exacta en
    el 422. Eso se cierra rediseñando la recepción, no con permisos.
    """
    for (path, metodo), guardia in MATRIZ.items():
        if guardia is not puede_ver_cantidades:
            continue
        assert puede_ver_cantidades in _guardias_de(_buscar(path, metodo)), (
            f"{metodo} {path} lleva cantidades y quedó alcanzable por bodega"
        )
