# app/services/color_service.py
"""El catálogo de colores de una empresa."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.color import Color, normalizar
from app.models.lote import Lote
from app.repositories.base import BaseRepository
from app.schemas.corte import ColorCreate, ColorOut, ColorUpdate


class ColorRepository(BaseRepository[Color]):
    def __init__(self, db: Session):
        super().__init__(Color, db)

    def listar(self, empresa_id: int, incluir_inactivos: bool = False) -> list[Color]:
        stmt = select(Color).where(Color.empresa_id == empresa_id)
        if not incluir_inactivos:
            stmt = stmt.where(Color.activo.is_(True))
        return list(self.db.execute(stmt.order_by(Color.nombre)).scalars().all())

    def nombres_normalizados(self, empresa_id: int) -> list[str]:
        """Para avisar en la importación cuando un color ya está en el catálogo."""
        stmt = select(Color.nombre_normalizado).where(Color.empresa_id == empresa_id)
        return list(self.db.execute(stmt).scalars().all())

    def buscar_por_nombre(self, empresa_id: int, nombre: str) -> Color | None:
        stmt = select(Color).where(
            Color.empresa_id == empresa_id,
            Color.nombre_normalizado == normalizar(nombre),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def esta_en_uso(self, color_id: int, empresa_id: int) -> bool:
        stmt = select(Lote.id).where(
            Lote.color_id == color_id, Lote.empresa_id == empresa_id
        ).limit(1)
        return self.db.execute(stmt).scalar_one_or_none() is not None


class ColorService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ColorRepository(db)

    def listar(self, empresa_id: int, incluir_inactivos: bool = False) -> list[ColorOut]:
        return [
            ColorOut.model_validate(color)
            for color in self.repo.listar(empresa_id, incluir_inactivos)
        ]

    def crear(self, empresa_id: int, data: ColorCreate) -> ColorOut:
        if self.repo.buscar_por_nombre(empresa_id, data.nombre) is not None:
            # Se compara normalizado, así que "Azul Rey" choca con "azul rey".
            # Es el punto entero de tener catálogo: que el mismo color no
            # exista tres veces escrito distinto.
            raise ConflictError(f"Ya tienes un color que se llama así: {data.nombre}")

        color = Color(
            empresa_id=empresa_id,
            nombre=data.nombre,
            nombre_normalizado=normalizar(data.nombre),
            hex=data.hex,
        )
        self.db.add(color)
        self.db.commit()
        self.db.refresh(color)
        return ColorOut.model_validate(color)

    def actualizar(self, id: int, empresa_id: int, data: ColorUpdate) -> ColorOut:
        color = self._buscar(id, empresa_id)
        cambios = data.model_dump(exclude_unset=True)

        if "nombre" in cambios and cambios["nombre"] is not None:
            otro = self.repo.buscar_por_nombre(empresa_id, cambios["nombre"])
            if otro is not None and otro.id != color.id:
                raise ConflictError(f"Ya tienes un color que se llama así: {cambios['nombre']}")
            color.nombre = " ".join(cambios["nombre"].split())
            color.nombre_normalizado = normalizar(color.nombre)
            cambios.pop("nombre")

        for campo, valor in cambios.items():
            setattr(color, campo, valor)
        self.db.commit()
        self.db.refresh(color)
        return ColorOut.model_validate(color)

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Baja lógica si el color ya se usó, borrado de verdad si no.

        Un color que aparece en un corte viejo no se puede borrar sin dejar esa
        línea sin color, y eso es perder historia. Pero un color que se creó
        con un dedazo y nunca se usó sí debe poder desaparecer -- si no, el
        catálogo se llena de basura que nadie se atreve a tocar.
        """
        color = self._buscar(id, empresa_id)
        if self.repo.esta_en_uso(color.id, empresa_id):
            if not color.activo:
                raise ValidationError("Ese color ya estaba desactivado")
            color.activo = False
        else:
            self.db.delete(color)
        self.db.commit()

    def _buscar(self, id: int, empresa_id: int) -> Color:
        color = self.repo.get_by_id(id, empresa_id)
        if color is None:
            raise NotFoundError("No encontramos ese color")
        return color
