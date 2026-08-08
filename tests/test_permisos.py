# tests/test_permisos.py
"""
El mapa de permisos de la API.

Verifica sobre las rutas ya registradas qué endpoints exigen rol de
administrador. Es una prueba estructural a propósito: no necesita levantar
un servidor ni emitir tokens, y aun así falla si alguien quita una guardia
sin darse cuenta -- que es exactamente como se abren estos huecos.

El caso que motivó este archivo: el ranking de talleres y su Excel quedaron
abiertos a cualquier usuario cuando se les agregó el monto a pagar, así que
un operario podía ver cuánto se le paga a cada taller.
"""
from fastapi.routing import APIRoute

from app.core.deps import require_admin
from app.main import app

# Rutas que muestran plata: cuánto se le paga a cada taller. Es información
# de proveedores, no un tablero de producción.
RUTAS_SOLO_ADMIN = (
    ("/api/v1/ranking/talleres", "GET"),
    ("/api/v1/ranking/talleres.xlsx", "GET"),
    # La carga masiva crea decenas de talleres y productos de una vez.
    ("/api/v1/importacion/previsualizar", "POST"),
    ("/api/v1/importacion/confirmar", "POST"),
    ("/api/v1/importacion/plantilla.xlsx", "GET"),
)

# Rutas que deben seguir abiertas a los operarios: son su trabajo diario.
# Si alguien las cierra por exceso de celo, la empresa no puede operar.
RUTAS_DE_TODOS = (
    ("/api/v1/resumen", "GET"),
    ("/api/v1/asignaciones", "GET"),
    ("/api/v1/lotes", "GET"),
    ("/api/v1/talleres", "GET"),
)


def _dependencias(dependant, vistas=None) -> set:
    """Todas las funciones de las que depende un endpoint, incluidas las
    anidadas (require_admin depende a su vez de get_current_usuario)."""
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


def test_las_rutas_con_plata_exigen_administrador():
    for path, metodo in RUTAS_SOLO_ADMIN:
        ruta = _buscar(path, metodo)
        assert require_admin in _dependencias(ruta.dependant), (
            f"{metodo} {path} quedó sin la guardia de administrador"
        )


def test_las_rutas_de_operacion_diaria_no_exigen_administrador():
    """La otra mitad: cerrar de más también rompe el negocio. Un operario
    tiene que poder ver los lotes y registrar devoluciones."""
    for path, metodo in RUTAS_DE_TODOS:
        ruta = _buscar(path, metodo)
        assert require_admin not in _dependencias(ruta.dependant), (
            f"{metodo} {path} quedó cerrado a los operarios sin necesidad"
        )
