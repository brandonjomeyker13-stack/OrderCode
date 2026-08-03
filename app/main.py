# app/main.py
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

logging.basicConfig(level=logging.INFO if Settings().is_production else logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    # Oculta /docs y /redoc en producción -- no hace falta exponer el
    # esquema completo de la API públicamente una vez esto se venda.
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # necesario para que la cookie de refresh viaje
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Mapeo de excepciones de negocio -> códigos HTTP ---
# Los services nunca importan FastAPI: lanzan AppError y sus subclases,
# y aquí se traduce a la respuesta HTTP correspondiente en un solo lugar.

_ERROR_STATUS_MAP = {
    NotFoundError: 404,
    ConflictError: 409,
    UnauthorizedError: 401,
    ForbiddenError: 403,
    ValidationError: 422,
}


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError):
    status_code = _ERROR_STATUS_MAP.get(type(exc), 400)
    return JSONResponse(status_code=status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    # Nunca se filtra el mensaje real de un error inesperado al cliente
    # (podría exponer detalles internos, rutas de archivos, etc.).
    # Se loguea completo del lado del servidor para poder depurarlo.
    logger.exception("Error no controlado en %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
def health_check():
    return {"status": "ok"}