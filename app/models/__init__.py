# app/models/__init__.py
"""
Importa todos los modelos aquí para que:
1. Alembic pueda detectarlos vía Base.metadata al hacer autogenerate.
2. Las relationships con strings ("Usuario", "Empresa", etc.) se resuelvan
   correctamente sin importar el orden en que se usen en otros archivos.
"""
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.models.qr_code import QRCode
from app.models.tipo_producto import TipoProducto
from app.models.taller import Taller
from app.models.lote import Lote
from app.models.asignacion_taller import AsignacionTaller
from app.models.incidencia import Incidencia
from app.models.cliente import Cliente
from app.models.refresh_token import RefreshToken
from app.models.idempotency_key import IdempotencyKey
from app.models.password_reset_token import PasswordResetToken
from app.models.notificacion_whatsapp import NotificacionWhatsapp

__all__ = [
    "Empresa",
    "Usuario",
    "QRCode",
    "TipoProducto",
    "Taller",
    "Lote",
    "AsignacionTaller",
    "Incidencia",
    "Cliente",
    "RefreshToken",
    "IdempotencyKey",
    "PasswordResetToken",
    "NotificacionWhatsapp",
]