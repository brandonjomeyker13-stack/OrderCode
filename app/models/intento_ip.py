# app/models/intento_ip.py
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class IntentoIP(Base, TimestampMixin):
    """
    Contador de llamadas por IP a los endpoints públicos, para frenar abuso
    (creación masiva de cuentas, quemar la cuota de correo pidiendo mil
    recuperaciones de contraseña).

    Va en la base y no en memoria a propósito: en memoria se pierde en cada
    despliegue -- y Render reinicia seguido -- así que bastaría con esperar
    un redeploy para saltarse el límite. Además dejaría de funcionar el día
    que haya más de una instancia.
    """
    __tablename__ = "intentos_ip"
    __table_args__ = (UniqueConstraint("ip", "ruta", name="uq_intento_ip_ruta"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False, index=True)
    ruta: Mapped[str] = mapped_column(String(100), nullable=False)
    intentos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Inicio de la ventana actual: cuando vence, el contador arranca de cero.
    ventana_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
