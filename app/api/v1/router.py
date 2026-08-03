# app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.endpoints import (
    asignaciones,
    auth,
    clientes,
    empresas,
    incidencias,
    lotes,
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
api_router.include_router(lotes.router)
api_router.include_router(asignaciones.router)
api_router.include_router(incidencias.router)
api_router.include_router(clientes.router)