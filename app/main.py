# app/main.py
import logging

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.db.session import engine
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
    # Content-Disposition va por lo mismo: sin exponerlo, la descarga del
    # Excel llega bien pero el front no puede leer el nombre del archivo y
    # termina guardándolo con un nombre aleatorio.
    expose_headers=["X-Total-Count", "Content-Disposition"],
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
    """¿Está vivo el proceso? Nada más.

    Es tonto A PROPÓSITO. Lo usa Render para decidir si el servicio arrancó,
    y si acá se consultara la base, un parpadeo de Supabase haría que Render
    reiniciara el servicio en bucle -- convirtiendo una caída de dos minutos
    de la base en una caída larga de toda la app.
    """
    return {"status": "ok"}


@app.get("/listo")
def readiness_check():
    """¿Puede la app atender de verdad? Esto sí comprueba la base.

    Este es el que debe vigilar el monitor de caída externo. `/health`
    respondería "ok" con la base caída, o sea que el monitor estaría en
    verde mientras ningún usuario puede entrar: un chequeo que no comprueba
    nada es peor que ninguno, porque da confianza falsa.

    De paso, al tocar la base mantiene despierto también al proyecto de
    Supabase, que en plan gratuito se pausa tras varios días sin actividad.
    """
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except Exception:
        # Se registra en el log pero NO se manda a Sentry: el monitor pega
        # cada pocos minutos, así que una caída de una tarde generaría
        # cientos de eventos idénticos. Quien avisa acá es el monitor.
        logger.error("La base de datos no responde", exc_info=True)
        # Cuerpo genérico a propósito: el mensaje de un error de conexión
        # suele traer la cadena de conexión completa, con usuario y
        # contraseña. Este endpoint es público.
        return JSONResponse(
            status_code=503, content={"status": "sin_base_de_datos"}
        )

    return {"status": "ok"}