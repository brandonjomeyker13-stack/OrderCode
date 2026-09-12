# app/repositories/venta_repository.py
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.lote import Lote
from app.models.venta import Venta
from app.repositories.base import BaseRepository


class VentaRepository(BaseRepository[Venta]):
    def __init__(self, db: Session):
        super().__init__(Venta, db)

    def listar(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[Venta]:
        stmt = (
            select(Venta)
            .where(Venta.empresa_id == empresa_id)
            .options(selectinload(Venta.lote).selectinload(Lote.tipo_producto))
            .order_by(Venta.fecha.desc(), Venta.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def vendido_por_lote(self, lote_ids: list[int], empresa_id: int) -> dict[int, int]:
        """Cuánto se ha sacado de cada lote, en UNA consulta."""
        if not lote_ids:
            return {}
        stmt = (
            select(Venta.lote_id, func.coalesce(func.sum(Venta.cantidad), 0))
            .where(Venta.lote_id.in_(lote_ids), Venta.empresa_id == empresa_id)
            .group_by(Venta.lote_id)
        )
        return {fila[0]: fila[1] for fila in self.db.execute(stmt).all()}

    def vendido_de(self, lote_id: int, empresa_id: int) -> int:
        stmt = select(func.coalesce(func.sum(Venta.cantidad), 0)).where(
            Venta.lote_id == lote_id, Venta.empresa_id == empresa_id
        )
        return self.db.execute(stmt).scalar_one()

    def devuelto_por_lote(self, lote_ids: list[int], empresa_id: int) -> dict[int, int]:
        """Unidades que volvieron BIEN de los talleres, por lote.

        Suma `devoluciones`, no la merma: lo dañado no está listo para vender.
        Y suma solo lo que existe en esa tabla, que con el flujo nuevo son las
        devoluciones YA CONFIRMADAS por corte -- un conteo de bodega que nadie
        ha revisado todavía no cuenta como inventario, y esa es justamente la
        razón de que la confirmación exista.
        """
        if not lote_ids:
            return {}
        stmt = (
            select(
                AsignacionTaller.lote_id,
                func.coalesce(func.sum(Devolucion.cantidad), 0),
            )
            .join(Devolucion, Devolucion.asignacion_id == AsignacionTaller.id)
            .where(
                AsignacionTaller.lote_id.in_(lote_ids),
                AsignacionTaller.empresa_id == empresa_id,
            )
            .group_by(AsignacionTaller.lote_id)
        )
        return {fila[0]: fila[1] for fila in self.db.execute(stmt).all()}

    def devuelto_de(self, lote_id: int, empresa_id: int) -> int:
        return self.devuelto_por_lote([lote_id], empresa_id).get(lote_id, 0)
