# app/models/tipo_producto.py
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base 
from app.db.mixins import TimestampMixin


class TipoProducto(Base, TimestampMixin):
    """
    Catálogo de tipos de producto que fabrica la empresa.
    Genérico a propósito: para una confeccionista puede ser "legging",
    para una empresa de calzado puede ser "bota de cuero talla 38", etc.
    """
    __tablename__ = "tipos_producto"
    __table_args__ = (
        UniqueConstraint("empresa_id", "referencia", name="uq_tipo_producto_referencia_empresa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    referencia: Mapped[str] = mapped_column(String(50), nullable=False)

    # Lo que se le paga al taller por cada unidad de este producto. Es el
    # precio VIGENTE y se puede cambiar cuando suba la mano de obra: las
    # asignaciones se llevan una copia al crearse (ver AsignacionTaller), así
    # que subirlo no altera los cortes ya pagados.
    #
    # Opcional: una empresa puede usar la app solo para control de producción,
    # sin cargar precios. Numeric y no Float -- la plata no se guarda en coma
    # flotante, donde 0.1 + 0.2 no da 0.3.
    precio_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    qr_code_id: Mapped[int] = mapped_column(
        ForeignKey("qr_codes.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    qr_code: Mapped["QRCode"] = relationship()