# app/core/exceptions.py


class AppError(Exception):
    """Excepción base de errores de negocio. Se traduce a HTTP en main.py,
    para que los services nunca importen FastAPI/HTTPException directamente
    y se mantengan independientes del framework web.

    `codigo` es opcional y es para las máquinas, no para las personas: el
    mensaje se escribe para quien lo lee en pantalla y por eso cambia; el
    código no cambia y sirve para que el cliente distinga DOS 403 que no se
    parecen en nada. Sin él, el front tenía que adivinar por el texto.
    """

    def __init__(self, message: str, codigo: str | None = None):
        self.message = message
        self.codigo = codigo
        super().__init__(message)


class NotFoundError(AppError):
    """-> HTTP 404"""


class ConflictError(AppError):
    """-> HTTP 409 (ej. email duplicado, referencia duplicada)"""


class UnauthorizedError(AppError):
    """-> HTTP 401 (credenciales inválidas, token inválido/expirado)"""


class ForbiddenError(AppError):
    """-> HTTP 403 (autenticado pero sin permiso para esta acción)"""


#: La empresa entera no tiene acceso: pendiente de activar o pausada por falta
#: de pago. Afecta a TODA la aplicación y solo lo resuelve el dueño.
EMPRESA_INACTIVA = "empresa_inactiva"

#: Esta persona, en su puesto, no puede hacer ESTA acción. La sesión está bien
#: y el resto de la aplicación le sigue funcionando. Distinguirlo de lo
#: anterior es la diferencia entre "no es para ti" y "debes plata".
ROL_INSUFICIENTE = "rol_insuficiente"


class ValidationError(AppError):
    """-> HTTP 422 (regla de negocio violada, ej. cantidad excede disponible)"""


class RateLimitedError(AppError):
    """-> HTTP 429 (ej. cuenta bloqueada temporalmente por intentos fallidos
    de login). Lleva retry_after_seconds para que main.py pueda mandar el
    header Retry-After, que es lo que un cliente HTTP espera para saber
    cuándo reintentar."""

    def __init__(self, message: str, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)
