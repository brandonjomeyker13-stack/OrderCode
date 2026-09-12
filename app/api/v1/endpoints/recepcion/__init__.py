# app/api/v1/endpoints/recepcion/__init__.py
"""
Las rutas de la recepción, una carpeta por proceso y un archivo por puesto.

`bodega.py` y `corte.py` montan bajo el mismo prefijo `/recepcion` porque son
dos mitades del mismo trámite, pero no comparten ni un schema de salida: lo
que devuelve bodega.py no declara ninguna cantidad enviada, y lo que devuelve
corte.py las declara todas. Esa es la separación que pidió el negocio, escrita
donde no se puede olvidar.
"""
from fastapi import APIRouter

from app.api.v1.endpoints.recepcion import bodega, corte

router = APIRouter(prefix="/recepcion", tags=["recepcion"])
router.include_router(bodega.router)
router.include_router(corte.router)
