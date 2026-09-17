# app/repositories/asignacion_taller_repository.py
from __future__ import annotations

from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.color import Color, normalizar
from app.models.enums import EstadoAsignacion
from app.models.lote import Lote
from app.repositories.base import BaseRepository
from app.schemas.filtros import FiltrosAsignacion


class AsignacionTallerRepository(BaseRepository[AsignacionTaller]):
    def __init__(self, db: Session):
        super().__init__(AsignacionTaller, db)

    # Se precargan en bloque las relaciones que SIEMPRE se serializan en la
    # salida. Sin esto, cada fila del listado dispara una consulta extra por
    # relación -- el N+1 clásico.
    _PRECARGA_RELACIONES = (
        selectinload(AsignacionTaller.taller),
        selectinload(AsignacionTaller.devoluciones),
    )

    def get_by_id(self, id: int, empresa_id: int) -> AsignacionTaller | None:
        stmt = (
            select(AsignacionTaller)
            .options(*self._PRECARGA_RELACIONES)
            .where(AsignacionTaller.id == id, AsignacionTaller.empresa_id == empresa_id)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id_bloqueando(self, id: int, empresa_id: int) -> AsignacionTaller | None:
        """Con lock de fila, para registrar devoluciones y mermas: sin él, dos
        registros simultáneos leen el mismo pendiente y ambos pasan la
        validación, devolviendo más de lo que el taller tenía.

        Sin selectinload: no se puede combinar FOR UPDATE con el join que
        precarga el taller. Quien necesite el taller lo carga después, ya
        dentro de la transacción."""
        stmt = (
            select(AsignacionTaller)
            .where(AsignacionTaller.id == id, AsignacionTaller.empresa_id == empresa_id)
            .with_for_update()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _aplicar_filtros(stmt: Select, filtros: FiltrosAsignacion | None) -> Select:
        """Punto único donde se traducen los filtros a SQL, para que el
        listado y el conteo (X-Total-Count) no se puedan desincronizar."""
        if filtros is None:
            return stmt
        if filtros.taller_id is not None:
            stmt = stmt.where(AsignacionTaller.taller_id == filtros.taller_id)
        if filtros.corte_id is not None:
            stmt = stmt.join(Lote, Lote.id == AsignacionTaller.lote_id).where(
                Lote.corte_id == filtros.corte_id
            )
        if filtros.lote_id is not None:
            stmt = stmt.where(AsignacionTaller.lote_id == filtros.lote_id)
        if filtros.estado is not None:
            stmt = stmt.where(AsignacionTaller.estado == filtros.estado)
        if filtros.desde is not None:
            stmt = stmt.where(AsignacionTaller.fecha_asignacion >= filtros.desde)
        if filtros.hasta is not None:
            stmt = stmt.where(AsignacionTaller.fecha_asignacion <= filtros.hasta)
        return stmt

    def list(
        self,
        empresa_id: int,
        offset: int = 0,
        limit: int = 50,
        filtros: FiltrosAsignacion | None = None,
    ) -> list[AsignacionTaller]:
        """Override: misma precarga de taller que get_by_id, más los filtros
        opcionales aplicados en SQL."""
        stmt = (
            select(AsignacionTaller)
            .options(*self._PRECARGA_RELACIONES)
            .where(AsignacionTaller.empresa_id == empresa_id)
        )
        stmt = self._aplicar_filtros(stmt, filtros)
        stmt = stmt.order_by(AsignacionTaller.id.desc()).offset(offset).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def count(self, empresa_id: int, filtros: FiltrosAsignacion | None = None) -> int:
        """Override: el total tiene que reflejar los mismos filtros que el
        listado, si no la paginación del front queda mal."""
        stmt = (
            select(func.count())
            .select_from(AsignacionTaller)
            .where(AsignacionTaller.empresa_id == empresa_id)
        )
        return self.db.execute(self._aplicar_filtros(stmt, filtros)).scalar_one()

    def listar_atrasadas(
        self, empresa_id: int, fecha_limite: date
    ) -> list[AsignacionTaller]:
        """Asignaciones que el taller todavía no termina y que salieron en o
        antes de `fecha_limite` -- o sea, las que llevan demasiado tiempo
        fuera sin cerrarse.

        Se excluyen las ENTREGADO_COMPLETO: esas ya volvieron (o se
        resolvieron con merma) y no hay nada pendiente que reclamar."""
        stmt = (
            select(AsignacionTaller)
            .options(
                selectinload(AsignacionTaller.taller),
                # El resumen muestra el producto de cada atraso: sin precargar
                # esto, sería una consulta por fila.
                selectinload(AsignacionTaller.lote).selectinload(Lote.tipo_producto),
            )
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.estado != EstadoAsignacion.ENTREGADO_COMPLETO,
                AsignacionTaller.fecha_asignacion <= fecha_limite,
            )
            # Lo más viejo primero: es lo más urgente.
            .order_by(AsignacionTaller.fecha_asignacion.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def listar_por_estados(
        self,
        empresa_id: int,
        estados: list[EstadoAsignacion],
        offset: int = 0,
        limit: int = 50,
    ) -> list[AsignacionTaller]:
        """Las asignaciones que están en alguno de esos estados.

        La usa la lista de bodega ("qué puede llegar hoy"). Filtra por ESTADO
        y no por saldo a propósito: una consulta que preguntara "¿a cuánto le
        falta?" traería la cantidad enviada hasta esa capa, y de ahí a una
        respuesta hay un descuido de distancia. Bodega cuenta a ciegas.
        """
        stmt = (
            select(AsignacionTaller)
            .options(
                selectinload(AsignacionTaller.taller),
                selectinload(AsignacionTaller.lote).options(
                    selectinload(Lote.tipo_producto),
                    selectinload(Lote.color),
                    selectinload(Lote.corte),
                ),
            )
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.estado.in_(estados),
            )
            .order_by(AsignacionTaller.fecha_asignacion.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTaller]:
        stmt = (
            select(AsignacionTaller)
            .options(*self._PRECARGA_RELACIONES)
            .where(
                AsignacionTaller.lote_id == lote_id,
                AsignacionTaller.empresa_id == empresa_id,
            )
            .order_by(AsignacionTaller.fecha_asignacion.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def buscar_pendiente_por_pieza(
        self,
        empresa_id: int,
        taller_id: int,
        tipo_producto_id: int,
        color: str,
        corte_id: int | None = None,
    ) -> AsignacionTaller | None:
        """El envío más viejo de ese taller que todavía no cierra, de esa
        prenda y color. Si hay dos proporciones al mismo taller, entra la
        primera que sigue pendiente."""
        clave = normalizar(color)
        stmt = (
            select(AsignacionTaller)
            .join(Lote, Lote.id == AsignacionTaller.lote_id)
            .outerjoin(Color, Color.id == Lote.color_id)
            .options(
                selectinload(AsignacionTaller.taller),
                selectinload(AsignacionTaller.lote).options(
                    selectinload(Lote.tipo_producto),
                    selectinload(Lote.color),
                    selectinload(Lote.corte),
                ),
            )
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                AsignacionTaller.taller_id == taller_id,
                AsignacionTaller.estado.in_(
                    [EstadoAsignacion.ASIGNADO, EstadoAsignacion.ENTREGADO_PARCIAL]
                ),
                Lote.tipo_producto_id == tipo_producto_id,
                or_(
                    Lote.color_nombre_normalizado == clave,
                    Color.nombre_normalizado == clave,
                ),
            )
            .order_by(AsignacionTaller.fecha_asignacion.asc(), AsignacionTaller.id.asc())
        )
        if corte_id is not None:
            stmt = stmt.where(Lote.corte_id == corte_id)
        return self.db.execute(stmt).scalars().first()