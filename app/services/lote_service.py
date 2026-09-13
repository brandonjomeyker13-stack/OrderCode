# app/services/lote_service.py
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.enums import EstadoLote
from app.models.lote import Lote
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.tipo_producto_repository import TipoProductoRepository
from app.services.corte_service import etiqueta_de
from app.schemas.lote import LoteConDisponibilidad, LoteCreate, LoteUpdate

# Ver el comentario de RUTA_CREAR en asignacion_taller_service.
RUTA_CREAR = "POST /lotes"


class LoteService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = LoteRepository(db)
        self.tipo_producto_repo = TipoProductoRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)

    def crear(
        self, empresa_id: int, data: LoteCreate, idempotency_key: str | None = None
    ) -> Lote:
        """La Idempotency-Key es opcional, igual que en asignaciones: sin ella
        el comportamiento es el de siempre. Con ella, el doble clic (o el
        reintento del cliente tras un timeout de red que en realidad sí llegó)
        devuelve el lote que ya se creó en vez de crear otro idéntico."""
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "lote", RUTA_CREAR
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        tipo_producto = self.tipo_producto_repo.get_by_id(data.tipo_producto_id, empresa_id)
        if tipo_producto is None:
            raise NotFoundError("Tipo de producto no encontrado")

        lote = self.repo.create(
            Lote(empresa_id=empresa_id, estado=EstadoLote.PENDIENTE_ASIGNACION, **data.model_dump())
        )

        # El lote y su clave se confirman en el mismo commit: si dos requests
        # con la misma clave corren a la vez, el UNIQUE decide cuál gana y la
        # que pierde reusa el resultado de la ganadora en vez de reventar.
        reclamar_clave(self.db, empresa_id, idempotency_key, RUTA_CREAR, "lote", lote.id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "lote", RUTA_CREAR
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            raise ValidationError("No se pudo crear el lote, intenta de nuevo")

        self.db.refresh(lote)
        return lote

    def obtener(self, id: int, empresa_id: int) -> Lote:
        lote = self.repo.get_by_id(id, empresa_id)
        if lote is None:
            raise NotFoundError("Lote no encontrado")
        return lote

    def _armar(self, lote: Lote, asignado: int) -> LoteConDisponibilidad:
        # Ver el comentario de construir_asignacion_out: los campos se
        # enumeran para que una columna nueva no se filtre sola.
        return LoteConDisponibilidad(
            id=lote.id,
            empresa_id=lote.empresa_id,
            cantidad_total=lote.cantidad_total,
            fecha_registro=lote.fecha_registro,
            fecha_entrega_cliente=lote.fecha_entrega_cliente,
            estado=lote.estado,
            created_at=lote.created_at,
            updated_at=lote.updated_at,
            tipo_producto=lote.tipo_producto,
            cantidad_asignada_total=asignado,
            cantidad_disponible=lote.cantidad_total - asignado,
            color=lote.color.nombre if lote.color else None,
            corte=etiqueta_de(lote.corte) if lote.corte else None,
        )

    def _con_disponibilidad(self, lote: Lote, empresa_id: int) -> LoteConDisponibilidad:
        return self._armar(lote, self.repo.calcular_cantidad_asignada(lote.id, empresa_id))

    def _lista_con_disponibilidad(
        self, lotes: list[Lote], empresa_id: int
    ) -> list[LoteConDisponibilidad]:
        """Una sola consulta para lo asignado de todos los lotes, en vez de
        una por lote."""
        asignados = self.repo.asignado_por_lote([l.id for l in lotes], empresa_id)
        return [self._armar(lote, asignados.get(lote.id, 0)) for lote in lotes]

    def listar_activos_por_tipo_producto(
        self, tipo_producto_id: int, empresa_id: int
    ) -> list[LoteConDisponibilidad]:
        """La query central de la vista de escaneo QR en tiempo real."""
        lotes = self.repo.listar_activos_por_tipo_producto(tipo_producto_id, empresa_id)
        return self._lista_con_disponibilidad(lotes, empresa_id)

    def cerrar_hacia_cliente(self, id: int, empresa_id: int, fecha_entrega: date) -> Lote:
        lote = self.obtener(id, empresa_id)
        if lote.estado != EstadoLote.ENTREGADO_COMPLETO:
            raise ValidationError(
                "Solo se puede cerrar hacia cliente un lote en estado 'entregado_completo'"
            )
        lote.estado = EstadoLote.CERRADO_CLIENTE
        lote.fecha_entrega_cliente = fecha_entrega
        self.db.commit()
        self.db.refresh(lote)
        return lote
    def listar(self, empresa_id: int, offset: int, limit: int) -> list[LoteConDisponibilidad]:
        lotes = self.repo.list(empresa_id, offset, limit)
        return self._lista_con_disponibilidad(lotes, empresa_id)

    def contar(self, empresa_id: int) -> int:
        return self.repo.count(empresa_id)

    def obtener_con_disponibilidad(self, id: int, empresa_id: int) -> LoteConDisponibilidad:
        lote = self.obtener(id, empresa_id)
        return self._con_disponibilidad(lote, empresa_id)

    def actualizar(self, id: int, empresa_id: int, data: LoteUpdate) -> LoteConDisponibilidad:
        """Corrección de un error de captura -- no toca el estado del lote."""
        lote = self.obtener(id, empresa_id)

        if data.cantidad_total is not None:
            ya_asignado = self.repo.calcular_cantidad_asignada(lote.id, empresa_id)
            if data.cantidad_total < ya_asignado:
                raise ValidationError(
                    f"No se puede bajar la cantidad total a {data.cantidad_total}: ya hay "
                    f"{ya_asignado} unidades asignadas a talleres"
                )
            lote.cantidad_total = data.cantidad_total

        if data.fecha_registro is not None:
            asignaciones = self.asignacion_repo.listar_por_lote(lote.id, empresa_id)
            primera_asignacion = min((a.fecha_asignacion for a in asignaciones), default=None)
            if primera_asignacion is not None and data.fecha_registro > primera_asignacion:
                raise ValidationError(
                    f"La fecha de registro ({data.fecha_registro}) no puede ser posterior a la "
                    f"fecha en que ya se asignó a un taller ({primera_asignacion})"
                )
            lote.fecha_registro = data.fecha_registro

        self.db.commit()
        self.db.refresh(lote)
        return self._con_disponibilidad(lote, empresa_id)

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Borrado físico, solo permitido si el lote todavía no tiene ninguna
        asignación -- si ya tiene, es historial real y no se debe poder
        destruir con un DELETE (la relación es cascade, la DB no lo
        bloquearía sola)."""
        lote = self.obtener(id, empresa_id)
        if self.asignacion_repo.listar_por_lote(lote.id, empresa_id):
            raise ConflictError(
                "No se puede eliminar: este lote ya tiene asignaciones a talleres registradas"
            )
        self.db.delete(lote)
        self.db.commit()