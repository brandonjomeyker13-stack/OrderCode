# app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.endpoints import (
    alertas,
    asignaciones,
    auth,
    cortes,
    empresas,
    importacion,
    incidencias,
    inventario,
    lotes,
    notificaciones,
    ranking,
    recepcion,
    resumen,
    talleres,
    tipos_producto,
    usuarios,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(empresas.router)
api_router.include_router(usuarios.router)
api_router.include_router(talleres.router)
api_router.include_router(tipos_producto.router)
# El corte y su catalogo de colores: la unidad real del negocio.
api_router.include_router(cortes.router)
api_router.include_router(lotes.router)
api_router.include_router(asignaciones.router)
api_router.include_router(incidencias.router)
# La recepcion tiene su propia carpeta: dos archivos, uno por puesto.
api_router.include_router(recepcion.router)
api_router.include_router(inventario.router)
api_router.include_router(resumen.router)
api_router.include_router(ranking.router)
api_router.include_router(importacion.router)
api_router.include_router(alertas.router)
api_router.include_router(notificaciones.router)