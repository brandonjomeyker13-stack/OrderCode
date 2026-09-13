# app/models/color.py
from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Color(Base, TimestampMixin):
    """
    Los colores que maneja una empresa.

    Es catálogo y no texto libre por una razón concreta: con texto libre, el
    mismo color se escribe "Azul rey", "azul rey" y "AZUL REY" en la misma
    semana, y entonces el inventario dice que hay tres colores donde hay uno.
    Con catálogo, el que teclea elige; y como cada maquila tiene su propia
    carta de colores, va por empresa y no como una lista fija del código.

    `nombre_normalizado` existe para comparar sin acentos ni mayúsculas: el
    UNIQUE va sobre él, así que "Azul Rey" y "azul rey" chocan al crearse --
    que es justo lo que se quiere -- mientras `nombre` conserva como lo
    escribió la persona, que es lo que se lee en pantalla.
    """

    __tablename__ = "colores"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre_normalizado", name="uq_color_nombre_empresa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(
        ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )

    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre_normalizado: Mapped[str] = mapped_column(String(60), nullable=False)
    #: El puntito de color del chip, si alguien se toma el trabajo de ponerlo.
    #: Opcional: un nombre bien escrito ya sirve para trabajar.
    hex: Mapped[str | None] = mapped_column(String(7), nullable=True)

    #: Baja lógica, nunca borrado físico: un color que ya se usó en un corte
    #: no se puede borrar sin romper el historial, pero sí dejar de ofrecerse.
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


def normalizar(nombre: str) -> str:
    """Minúsculas, sin acentos y sin espacios de sobra.

    Se usa al crear y al buscar, así que tiene que dar exactamente lo mismo en
    los dos sitios -- por eso vive aquí y no repetida en el service.
    """
    import unicodedata

    sin_acentos = "".join(
        letra
        for letra in unicodedata.normalize("NFD", nombre)
        if unicodedata.category(letra) != "Mn"
    )
    return " ".join(sin_acentos.lower().split())
