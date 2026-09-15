# app/services/inventario_service.py
"""Lo que ya está listo, y sacarlo."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.venta import Venta
from app.repositories.lote_repository import LoteRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.repositories.venta_repository import VentaRepository
from app.schemas.inventario import (
    LineaInventarioOut,
    LineaPanoramaOut,
    PanoramaOut,
    ResumenInventarioOut,
    TandaDisponibleOut,
    VentaCreate,
    VentaOut,
    VentaUpdate,
)
from app.services.corte_service import etiqueta_de

#: Identificador opaco de la operación ante Idempotency-Key. No es una URL.
RUTA_VENTA = "POST /inventario/ventas"


class InventarioService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = VentaRepository(db)
        self.lote_repo = LoteRepository(db)
        self.usuario_repo = UsuarioRepository(db)

    # --- Lectura ---

    def resumen(self, empresa_id: int, offset: int = 0, limit: int = 100) -> ResumenInventarioOut:
        """El inventario: lo que volvió bien y confirmado, menos lo vendido.

        Una fila por prenda y color, que es como se vende. Se listan solo las
        que tienen algo disponible: una tanda agotada no es inventario, es
        historia -- y la historia se mira en la lista de salidas, no aquí.

        El agrupado, el filtro y los totales los hace la base. Los totales son
        de la empresa entera: si se calcularan sobre la página, pedir la
        segunda daría un inventario distinto al de la primera. Y el agrupado
        va allá y no en el frontend porque agrupar solo lo que cupo en la
        página deja filas con menos unidades de las que hay.
        """
        grupos = self.repo.grupos_con_disponible(empresa_id, offset=offset, limit=limit)
        por_grupo: dict[tuple[int, int | None], list[TandaDisponibleOut]] = {}
        for lote, listo, salido in self.repo.tandas_con_disponible(
            empresa_id, [tipo.id for tipo, _color, _listo, _salido in grupos]
        ):
            por_grupo.setdefault((lote.tipo_producto_id, lote.color_id), []).append(
                TandaDisponibleOut(
                    lote_id=lote.id,
                    fecha_registro=lote.fecha_registro,
                    cantidad_disponible=listo - salido,
                )
            )

        lineas = [
            LineaInventarioOut(
                tipo_producto_id=tipo.id,
                producto=tipo.nombre,
                referencia=tipo.referencia,
                color=color.nombre if color else None,
                color_hex=color.hex if color else None,
                cantidad_lista=listo,
                cantidad_vendida=salido,
                cantidad_disponible=listo - salido,
                tandas=por_grupo.get((tipo.id, color.id if color else None), []),
            )
            for tipo, color, listo, salido in grupos
        ]

        return ResumenInventarioOut(
            total_disponible=self.repo.total_disponible(empresa_id),
            total_vendido=self.repo.total_vendido(empresa_id),
            total_lineas=self.repo.contar_grupos_con_disponible(empresa_id),
            lineas=lineas,
        )

    def panorama(self, empresa_id: int, offset: int = 0, limit: int = 100) -> PanoramaOut:
        """Qué hay y qué viene, por prenda y color.

        No es el inventario con otro nombre: aquí sí están los colores que
        siguen en el taller, que en el inventario no aparecen porque no se
        pueden despachar. Quien vende necesita las dos cosas para contestar
        "¿y si te mando 50 la otra semana?".
        """
        en_proceso, disponible = self.repo.totales_panorama(empresa_id)
        lineas = [
            LineaPanoramaOut(
                tipo_producto_id=tipo.id,
                producto=tipo.nombre,
                referencia=tipo.referencia,
                color=color.nombre if color else None,
                color_hex=color.hex if color else None,
                cantidad_cortada=cortada,
                cantidad_en_proceso=proceso,
                cantidad_perdida=perdida,
                cantidad_disponible=libre,
                cantidad_vendida=vendida,
            )
            for tipo, color, cortada, proceso, perdida, libre, vendida in self.repo.panorama(
                empresa_id, offset=offset, limit=limit
            )
        ]

        return PanoramaOut(
            total_en_proceso=en_proceso,
            total_disponible=disponible,
            total_lineas=self.repo.contar_panorama(empresa_id),
            lineas=lineas,
        )

    def listar_ventas(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[VentaOut]:
        return [
            self._armar(venta, empresa_id)
            for venta in self.repo.listar(empresa_id, offset=offset, limit=limit)
        ]

    def obtener(self, id: int, empresa_id: int) -> VentaOut:
        return self._armar(self._buscar(id, empresa_id), empresa_id)

    # --- Escritura ---

    def registrar(
        self,
        empresa_id: int,
        data: VentaCreate,
        usuario_id: int,
        idempotency_key: str | None = None,
    ) -> VentaOut:
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "venta", RUTA_VENTA
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        # Lock de fila del lote antes de leer disponible: sin él, dos salidas
        # concurrentes del mismo lote leen el mismo saldo y ambas pasan.
        lote = self.lote_repo.get_by_id_bloqueando(data.lote_id, empresa_id)
        if lote is None:
            raise NotFoundError("No encontramos ese lote")

        disponible = self._disponible(lote.id, empresa_id)
        if data.cantidad > disponible:
            # Este mensaje nombra la cifra y puede: lo lee ventas, que tiene
            # derecho a verla. No hay nada que ocultar en este extremo del
            # recorrido -- el conteo a ciegas es de bodega, no de aquí.
            raise ValidationError(
                f"Solo quedan {disponible} unidades disponibles de ese lote. "
                f"Si esperabas más, revisa con bodega si ya se confirmó lo que llegó."
            )

        venta = Venta(
            empresa_id=empresa_id,
            lote_id=lote.id,
            cantidad=data.cantidad,
            fecha=data.fecha,
            nota=data.nota,
            registrada_por_id=usuario_id,
        )
        self.db.add(venta)
        self.db.flush()

        reclamar_clave(self.db, empresa_id, idempotency_key, RUTA_VENTA, "venta", venta.id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "venta", RUTA_VENTA
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            raise ValidationError("No se pudo registrar la salida, intenta de nuevo")

        return self.obtener(venta.id, empresa_id)

    def actualizar(self, id: int, empresa_id: int, data: VentaUpdate) -> VentaOut:
        venta = self._buscar(id, empresa_id)
        cambios = data.model_dump(exclude_unset=True)

        if "cantidad" in cambios:
            # Mismo lock que al registrar: dos correcciones a la vez no deben
            # inventar unidades que no hay.
            if self.lote_repo.get_by_id_bloqueando(venta.lote_id, empresa_id) is None:
                raise NotFoundError("No encontramos ese lote")
            # El disponible de ahora ya descuenta ESTA venta, así que hay que
            # devolvérsela antes de comparar; si no, corregir 10 por 11 daría
            # "no hay disponible" aunque sobre de todo.
            margen = self._disponible(venta.lote_id, empresa_id) + venta.cantidad
            if cambios["cantidad"] > margen:
                raise ValidationError(
                    f"No alcanza: de ese lote solo hay {margen} unidades contando las de esta salida."
                )

        for campo, valor in cambios.items():
            setattr(venta, campo, valor)
        self.db.commit()
        return self.obtener(venta.id, empresa_id)

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Borrar la salida devuelve las unidades al inventario, porque el
        disponible se calcula y no se guarda."""
        venta = self._buscar(id, empresa_id)
        self.db.delete(venta)
        self.db.commit()

    # --- Internos ---

    def _disponible(self, lote_id: int, empresa_id: int) -> int:
        return self.repo.devuelto_de(lote_id, empresa_id) - self.repo.vendido_de(
            lote_id, empresa_id
        )

    def _buscar(self, id: int, empresa_id: int) -> Venta:
        venta = self.repo.get_by_id(id, empresa_id)
        if venta is None:
            raise NotFoundError("No encontramos esa salida")
        return venta

    def _armar(self, venta: Venta, empresa_id: int) -> VentaOut:
        nombre = None
        if venta.registrada_por_id is not None:
            usuario = self.usuario_repo.get_by_id(venta.registrada_por_id, empresa_id)
            nombre = usuario.nombre if usuario else None
        return VentaOut(
            id=venta.id,
            lote_id=venta.lote_id,
            producto=venta.lote.tipo_producto.nombre,
            referencia=venta.lote.tipo_producto.referencia,
            color=venta.lote.color.nombre if venta.lote.color else None,
            corte=etiqueta_de(venta.lote.corte) if venta.lote.corte else None,
            cantidad=venta.cantidad,
            fecha=venta.fecha,
            nota=venta.nota,
            registrada_por=nombre,
            created_at=venta.created_at,
            updated_at=venta.updated_at,
        )
