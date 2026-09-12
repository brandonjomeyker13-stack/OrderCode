# app/core/deps.py
from collections.abc import Callable

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.enums import RolUsuario
from app.models.usuario import Usuario

# auto_error=False: si no hay token, dejamos que sea get_current_usuario
# quien lance el error de negocio (UnauthorizedError), no FastAPI directo,
# así el formato de error es consistente en toda la API.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


def get_current_usuario(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if token is None:
        raise UnauthorizedError("No autenticado")

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise UnauthorizedError("Token inválido o expirado")

    usuario_id = payload.get("sub")
    if usuario_id is None:
        raise UnauthorizedError("Token inválido")

    usuario = db.get(Usuario, int(usuario_id))
    if usuario is None or not usuario.activo:
        raise UnauthorizedError("Usuario no válido")

    # Se revisa en cada request (no solo al iniciar sesión) para que pausar
    # una empresa por falta de pago tenga efecto de inmediato, incluso para
    # quien ya tenía una sesión abierta -- no hay que esperar a que expire
    # su access token (hasta 30 min) para que deje de poder usar la API.
    if not usuario.empresa.activo:
        raise ForbiddenError(
            "El acceso de tu empresa aún no está activo. Contacta al administrador para activarlo."
        )

    return usuario


def requiere_roles(
    *roles: RolUsuario, mensaje: str | None = None
) -> Callable[..., Usuario]:
    """Fábrica de guardias por rol.

    Es una fábrica y no una función escrita a mano por cada rol porque con
    varios roles hacen falta varias combinaciones, y cada copia de esta
    comprobación es un sitio más donde se puede olvidar poner la guardia --
    que es exactamente cómo se abren estos huecos en la práctica (ver el caso
    del ranking en tests/test_permisos.py).

    El mensaje se puede pasar a mano porque el texto lo lee un usuario: una
    lista generada de nombres de rol se entiende peor que una frase escrita.
    """
    permitidos = frozenset(roles)
    if not permitidos:
        raise ValueError("requiere_roles necesita al menos un rol")

    texto = mensaje or (
        "Esta acción requiere uno de estos roles: "
        + ", ".join(sorted(rol.value for rol in permitidos))
    )

    def guardia(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
        if usuario.rol not in permitidos:
            raise ForbiddenError(texto)
        return usuario

    return guardia


# Se conserva el nombre y el mensaje exactos: lo declaran ~15 endpoints y
# tests/test_permisos.py comprueba su presencia por identidad.
require_admin = requiere_roles(
    RolUsuario.ADMIN, mensaje="Esta acción requiere rol de administrador"
)

# --- Guardias por puesto ---
#
# Los nombres describen el TRABAJO, no una jerarquía: la separación entre quien
# manda al taller y quien cuenta lo que vuelve es el control central del
# producto, no un nivel de privilegio. ADMIN entra en todas porque es el
# respaldo operativo cuando falta alguien, no porque esté "por encima".

#: Registrar el corte, darlo de alta y mandarlo a los talleres.
requiere_corte = requiere_roles(
    RolUsuario.ADMIN,
    RolUsuario.CORTE,
    mensaje="Esta acción es de quien lleva el corte",
)

#: Contar y clasificar lo que devuelven los talleres. CORTE queda fuera a
#: propósito: quien manda al taller no puede ser quien cuenta lo que vuelve, o
#: el doble conteo se cierra sobre una sola persona y deja de ser un control.
requiere_bodega = requiere_roles(
    RolUsuario.ADMIN,
    RolUsuario.BODEGA,
    mensaje="Esta acción es de quien recibe en bodega",
)

#: Lectura compartida del día a día: catálogos y talleres, que las tres
#: personas necesitan para saber de qué producto y de qué taller están hablando.
requiere_operacion = requiere_roles(
    RolUsuario.ADMIN,
    RolUsuario.CORTE,
    RolUsuario.BODEGA,
    mensaje="Esta acción requiere un puesto de operación",
)

#: Respuestas que llevan cantidades: cuánto se cortó, cuánto se mandó, cuánto
#: queda pendiente. BODEGA queda fuera de TODAS, y no por jerarquía: cuenta a
#: ciegas, y ver la cifra esperada antes de contar anula el control entero.
#: Es requisito explícito del dueño, no una interpretación nuestra.
puede_ver_cantidades = requiere_roles(
    RolUsuario.ADMIN,
    RolUsuario.CORTE,
    RolUsuario.VENTAS,
    mensaje="Esta acción no está disponible para el puesto de bodega",
)
