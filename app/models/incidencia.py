# app/models/incidencia.py
from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.mixins import TimestampMixin
from app.models.enums import TipoIncidencia


class Incidencia(Base, TimestampMixin):
    """Daños/mermas, ligada a una asignación específica (taller + lote)."""
    __tablename__ = "incidencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asignacion_id: Mapped[int] = mapped_column(
        ForeignKey("asignaciones_taller.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tipo: Mapped[TipoIncidencia] = mapped_column(
        Enum(TipoIncidencia, name="tipo_incidencia_enum"), nullable=False
    )
    cantidad_afectada: Mapped[int] = mapped_column(Integer, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    asignacion: Mapped["AsignacionTaller"] = relationship(back_populates="incidencias")