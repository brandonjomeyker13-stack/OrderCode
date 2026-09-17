# app/models/corte_color.py
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class CorteColor(Base, TimestampMixin):
    """Las capas de un color en un tendido.

    El color se escribe a mano: no hay catálogo. "Negro" y "negro" son el
    mismo porque se compara normalizado, pero se guarda como lo tecleó Miriam.
    Las capas de todos los colores tienen que sumar las capas del corte.
    """

    __tablename__ = "corte_colores"
    __table_args__ = (
        UniqueConstraint(
            "corte_id", "nombre_normalizado", name="uq_corte_color_nombre"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    corte_id: Mapped[int] = mapped_column(
        ForeignKey("cortes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre_normalizado: Mapped[str] = mapped_column(String(60), nullable=False)
    capas: Mapped[int] = mapped_column(Integer, nullable=False)

    corte: Mapped["Corte"] = relationship(back_populates="colores")
