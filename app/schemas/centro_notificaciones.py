# app/schemas/centro_notificaciones.py
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TipoAviso(str, Enum):
    LOTE_ATRASADO = "lote_atrasado"
    ENVIO_FALLIDO = "envio_fallido"
    INCIDENCIA = "incidencia"


class Aviso(BaseModel):
    # Identidad estable del aviso (ej. "lote_atrasado:asignacion:42"), NO un
    # id numérico de tabla: los avisos se calculan al momento y no se guardan.
    # Es lo que se manda a POST /notificaciones/{id}/leer.
    id: str
    tipo: TipoAviso
    titulo: str
    mensaje: str
    # Ruta del front a la que debería llevar al tocarlo.
    enlace: str
    leida: bool
    # Cuándo ocurrió lo que originó el aviso, no cuándo se generó la respuesta.
    creada_at: datetime


class CentroNotificaciones(BaseModel):
    total: int
    no_leidas: int
    avisos: list[Aviso]
