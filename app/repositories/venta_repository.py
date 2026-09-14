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
            .options(
                selectinload(Venta.lote).options(
                    selectinload(Lote.tipo_producto),
                    selectinload(Lote.color),
                    selectinload(Lote.corte),
                )
            )
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

    # --- Inventario: el disponible se filtra y se suma en la base ---
    #
    # Traer una página de lotes y descartar en Python los agotados daba dos
    # mentiras a la vez: páginas medio vacías (o vacías del todo) y unos
    # totales que solo sumaban la página, no la empresa. Con muchos lotes
    # viejos, el inventario parecía estar en cero.

    def _devuelto_por_lote_sub(self, empresa_id: int):
        return (
            select(
                AsignacionTaller.lote_id.label("lote_id"),
                func.coalesce(func.sum(Devolucion.cantidad), 0).label("total"),
            )
            .join(Devolucion, Devolucion.asignacion_id == AsignacionTaller.id)
            .where(AsignacionTaller.empresa_id == empresa_id)
            .group_by(AsignacionTaller.lote_id)
            .subquery()
        )

    def _vendido_por_lote_sub(self, empresa_id: int):
        return (
            select(
                Venta.lote_id.label("lote_id"),
                func.coalesce(func.sum(Venta.cantidad), 0).label("total"),
            )
            .where(Venta.empresa_id == empresa_id)
            .group_by(Venta.lote_id)
            .subquery()
        )

    def _inventario_base(self, empresa_id: int):
        """Lotes con algo disponible, con sus dos cifras ya calculadas."""
        devuelto = self._devuelto_por_lote_sub(empresa_id)
        vendido = self._vendido_por_lote_sub(empresa_id)
        listo = func.coalesce(devuelto.c.total, 0)
        salido = func.coalesce(vendido.c.total, 0)
        origen = (
            select(Lote, listo.label("listo"), salido.label("salido"))
            .outerjoin(devuelto, devuelto.c.lote_id == Lote.id)
            .outerjoin(vendido, vendido.c.lote_id == Lote.id)
            .where(Lote.empresa_id == empresa_id, listo - salido > 0)
        )
        return origen, listo, salido

    def lotes_con_disponible(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[tuple[Lote, int, int]]:
        origen, _, _ = self._inventario_base(empresa_id)
        stmt = (
            origen.options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.corte),
            )
            .order_by(Lote.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(fila[0], fila[1], fila[2]) for fila in self.db.execute(stmt).all()]

    def contar_lotes_con_disponible(self, empresa_id: int) -> int:
        origen, _, _ = self._inventario_base(empresa_id)
        return self.db.execute(
            select(func.count()).select_from(origen.subquery())
        ).scalar_one()

    def total_disponible(self, empresa_id: int) -> int:
        """Lo disponible de TODA la empresa, no el de la página que se pidió."""
        origen, listo, salido = self._inventario_base(empresa_id)
        sub = origen.subquery()
        return self.db.execute(
            select(func.coalesce(func.sum(sub.c.listo - sub.c.salido), 0))
        ).scalar_one()

    def total_vendido(self, empresa_id: int) -> int:
        """Todo lo que ha salido, histórico completo."""
        return self.db.execute(
            select(func.coalesce(func.sum(Venta.cantidad), 0)).where(
                Venta.empresa_id == empresa_id
            )
        ).scalar_one()
