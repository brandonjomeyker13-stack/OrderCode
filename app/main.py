# app/main.py
import logging

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    ValidationError,
)
from app.core.monitoreo import configurar_sentry

logging.basicConfig(level=logging.INFO if settings.is_production else logging.DEBUG)
logger = logging.getLogger(__name__)

# Antes de crear la app: Sentry tiene que estar activo para poder instrumentar
# FastAPI y capturar también los errores que ocurran durante el arranque.
configurar_sentry()

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
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto el navegador recibe X-Total-Count pero el JS del front no
    # puede leerlo (los headers custom no son "simples" por default en CORS).
    expose_headers=["X-Total-Count"],
)


# --- Mapeo de excepciones de negocio -> códigos HTTP ---
_ERROR_STATUS_MAP = {
    NotFoundError: 404,
    ConflictError: 409,
    UnauthorizedError: 401,
    ForbiddenError: 403,
    ValidationError: 422,
    RateLimitedError: 429,
}


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError):
    status_code = _ERROR_STATUS_MAP.get(type(exc), 400)
    headers = {}
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(status_code=status_code, content={"detail": exc.message}, headers=headers)


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception):
    # Se reporta a mano porque este handler "atrapa" la excepción y Sentry ya
    # no la vería como no controlada -- justo los errores que más importa
    # conocer. Los AppError NO se reportan: son resultados de negocio
    # esperados (404, validación, etc.), no fallas del sistema, y llenarían
    # Sentry de ruido hasta volverlo inútil.
    sentry_sdk.capture_exception(exc)
    logger.exception("Error no controlado en %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"})


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
def health_check():
    return {"status": "ok"}