# app/repositories/venta_repository.py
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.asignacion_taller import AsignacionTaller
from app.models.color import Color
from app.models.devolucion import Devolucion
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.models.tipo_producto import TipoProducto
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
            # Las dos tablas llevan empresa: filtrar solo una deja la otra
            # agregando filas de todos los tenants para responderle a uno.
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                Devolucion.empresa_id == empresa_id,
            )
            .group_by(AsignacionTaller.lote_id)
            .subquery()
        )

    def _merma_por_lote_sub(self, empresa_id: int):
        """Lo dañado, por lote. No vuelve al inventario y tampoco sigue en el
        taller: sin restarlo, una prenda rota se queda 'en proceso' para
        siempre."""
        return (
            select(
                AsignacionTaller.lote_id.label("lote_id"),
                func.coalesce(func.sum(Incidencia.cantidad_afectada), 0).label("total"),
            )
            .join(Incidencia, Incidencia.asignacion_id == AsignacionTaller.id)
            .where(
                AsignacionTaller.empresa_id == empresa_id,
                Incidencia.empresa_id == empresa_id,
            )
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

    def _grupos_base(self, empresa_id: int):
        """Prenda + color, con las cifras de sus tandas ya sumadas.

        Agrupar aquí y no en el frontend es lo que hace que la paginación
        signifique algo: si la página fuera de tandas, un color repartido en
        varias podía quedar partido entre dos páginas y aparecer con menos de
        lo que hay. La página es de lo que se vende, que es prenda + color.

        El filtro de existencias sigue siendo POR TANDA, igual que antes: una
        tanda agotada no es inventario, es historia, y no debe sumar ni a lo
        listo ni a lo vendido de la fila.
        """
        devuelto = self._devuelto_por_lote_sub(empresa_id)
        vendido = self._vendido_por_lote_sub(empresa_id)
        listo = func.coalesce(devuelto.c.total, 0)
        salido = func.coalesce(vendido.c.total, 0)
        tandas = (
            select(
                Lote.tipo_producto_id.label("tipo_producto_id"),
                Lote.color_id.label("color_id"),
                listo.label("listo"),
                salido.label("salido"),
            )
            .outerjoin(devuelto, devuelto.c.lote_id == Lote.id)
            .outerjoin(vendido, vendido.c.lote_id == Lote.id)
            .where(Lote.empresa_id == empresa_id, listo - salido > 0)
            .subquery()
        )
        return select(
            tandas.c.tipo_producto_id,
            tandas.c.color_id,
            func.coalesce(func.sum(tandas.c.listo), 0).label("listo"),
            func.coalesce(func.sum(tandas.c.salido), 0).label("salido"),
        ).group_by(tandas.c.tipo_producto_id, tandas.c.color_id)

    def grupos_con_disponible(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[tuple[TipoProducto, Color | None, int, int]]:
        grupos = self._grupos_base(empresa_id).subquery()
        stmt = (
            select(TipoProducto, Color, grupos.c.listo, grupos.c.salido)
            .join(TipoProducto, TipoProducto.id == grupos.c.tipo_producto_id)
            .outerjoin(Color, Color.id == grupos.c.color_id)
            # Por nombre y no por id: la lista se lee buscando "Legging" y
            # luego "Negro". `is_(None)` deja los sin color al final sin
            # depender de NULLS LAST, que no todos los motores ordenan igual.
            # Los ids son el desempate, para que la página 2 no repita ni
            # se salte filas cuando dos productos se llaman igual.
            .order_by(
                TipoProducto.nombre,
                Color.nombre.is_(None),
                Color.nombre,
                grupos.c.tipo_producto_id,
                grupos.c.color_id,
            )
            .offset(offset)
            .limit(limit)
        )
        return [(fila[0], fila[1], fila[2], fila[3]) for fila in self.db.execute(stmt).all()]

    def contar_grupos_con_disponible(self, empresa_id: int) -> int:
        return self.db.execute(
            select(func.count()).select_from(self._grupos_base(empresa_id).subquery())
        ).scalar_one()

    def tandas_con_disponible(
        self, empresa_id: int, tipo_producto_ids: list[int]
    ) -> list[tuple[Lote, int, int]]:
        """Las tandas con existencias de esos productos, la más vieja primero.

        Van con la fila de inventario porque una salida se descuenta de UN
        lote: "20 negras" hay que traducirlo a lotes concretos, y quien vende
        no tiene por qué saber cuáles son.

        Se filtra por producto y no por producto+color para no armar un IN de
        tuplas con NULLs, que cada motor trata a su manera. Puede traer algún
        color que no esté en la página; el service se queda con los que
        necesita.
        """
        if not tipo_producto_ids:
            return []
        origen, _, _ = self._inventario_base(empresa_id)
        stmt = origen.where(Lote.tipo_producto_id.in_(tipo_producto_ids)).order_by(
            Lote.fecha_registro, Lote.id
        )
        return [(fila[0], fila[1], fila[2]) for fila in self.db.execute(stmt).all()]

    def total_disponible(self, empresa_id: int) -> int:
        """Lo disponible de TODA la empresa, no el de la página que se pidió."""
        origen, listo, salido = self._inventario_base(empresa_id)
        sub = origen.subquery()
        return self.db.execute(
            select(func.coalesce(func.sum(sub.c.listo - sub.c.salido), 0))
        ).scalar_one()

    # --- Panorama: el recorrido entero de cada prenda y color ---
    #
    # El inventario responde "qué puedo despachar". Esto responde "qué hay y
    # qué viene", que es otra pregunta: incluye lo que sigue en el taller, y
    # por eso no puede partir del filtro de existencias -- un color recién
    # cortado tiene disponible cero y aun así hay que verlo.

    def _panorama_base(self, empresa_id: int):
        devuelto = self._devuelto_por_lote_sub(empresa_id)
        perdido = self._merma_por_lote_sub(empresa_id)
        vendido = self._vendido_por_lote_sub(empresa_id)
        lotes = (
            select(
                Lote.tipo_producto_id.label("tipo_producto_id"),
                Lote.color_id.label("color_id"),
                Lote.cantidad_total.label("cortada"),
                func.coalesce(devuelto.c.total, 0).label("devuelta"),
                func.coalesce(perdido.c.total, 0).label("perdida"),
                func.coalesce(vendido.c.total, 0).label("vendida"),
            )
            .outerjoin(devuelto, devuelto.c.lote_id == Lote.id)
            .outerjoin(perdido, perdido.c.lote_id == Lote.id)
            .outerjoin(vendido, vendido.c.lote_id == Lote.id)
            .where(Lote.empresa_id == empresa_id)
            .subquery()
        )
        cortada = func.sum(lotes.c.cortada)
        devuelta = func.sum(lotes.c.devuelta)
        perdida = func.sum(lotes.c.perdida)
        vendida = func.sum(lotes.c.vendida)
        return (
            select(
                lotes.c.tipo_producto_id,
                lotes.c.color_id,
                cortada.label("cortada"),
                (cortada - devuelta - perdida).label("en_proceso"),
                perdida.label("perdida"),
                (devuelta - vendida).label("disponible"),
                vendida.label("vendida"),
            )
            .group_by(lotes.c.tipo_producto_id, lotes.c.color_id)
            # Lo que ya se cortó, se entregó y se vendió entero es historia:
            # deja de ocupar sitio en una pantalla que se lee para decidir hoy.
            .having((cortada - devuelta - perdida > 0) | (devuelta - vendida > 0))
        )

    def panorama(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[tuple[TipoProducto, Color | None, int, int, int, int, int]]:
        base = self._panorama_base(empresa_id).subquery()
        stmt = (
            select(
                TipoProducto,
                Color,
                base.c.cortada,
                base.c.en_proceso,
                base.c.perdida,
                base.c.disponible,
                base.c.vendida,
            )
            .join(TipoProducto, TipoProducto.id == base.c.tipo_producto_id)
            .outerjoin(Color, Color.id == base.c.color_id)
            .order_by(
                TipoProducto.nombre,
                Color.nombre.is_(None),
                Color.nombre,
                base.c.tipo_producto_id,
                base.c.color_id,
            )
            .offset(offset)
            .limit(limit)
        )
        return [tuple(fila) for fila in self.db.execute(stmt).all()]  # type: ignore[misc]

    def contar_panorama(self, empresa_id: int) -> int:
        return self.db.execute(
            select(func.count()).select_from(self._panorama_base(empresa_id).subquery())
        ).scalar_one()

    def totales_panorama(self, empresa_id: int) -> tuple[int, int]:
        """En proceso y disponible de la empresa entera, no de la página."""
        base = self._panorama_base(empresa_id).subquery()
        fila = self.db.execute(
            select(
                func.coalesce(func.sum(base.c.en_proceso), 0),
                func.coalesce(func.sum(base.c.disponible), 0),
            )
        ).one()
        return int(fila[0]), int(fila[1])

    def total_vendido(self, empresa_id: int) -> int:
        """Todo lo que ha salido, histórico completo."""
        return self.db.execute(
            select(func.coalesce(func.sum(Venta.cantidad), 0)).where(
                Venta.empresa_id == empresa_id
            )
        ).scalar_one()
