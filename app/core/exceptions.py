# app/core/exceptions.py


class AppError(Exception):
    """Excepción base de errores de negocio. Se traduce a HTTP en main.py,
    para que los services nunca importen FastAPI/HTTPException directamente
    y se mantengan independientes del framework web."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """-> HTTP 404"""


class ConflictError(AppError):
    """-> HTTP 409 (ej. email duplicado, referencia duplicada)"""


class UnauthorizedError(AppError):
    """-> HTTP 401 (credenciales inválidas, token inválido/expirado)"""


class ForbiddenError(AppError):
    """-> HTTP 403 (autenticado pero sin permiso para esta acción)"""


class ValidationError(AppError):
    """-> HTTP 422 (regla de negocio violada, ej. cantidad excede disponible)"""