# app/services/asignacion_taller_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoAsignacion, EstadoLote
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.taller_repository import TallerRepository
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerRegistrarDevolucion,
)


class AsignacionTallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)
        self.taller_repo = TallerRepository(db)

    def crear(self, empresa_id: int, data: AsignacionTallerCreate) -> AsignacionTaller:
        lote = self.lote_repo.get_by_id(data.lote_id, empresa_id)
        if lote is None:
            raise NotFoundError("Lote no encontrado")
        if lote.estado == EstadoLote.CERRADO_CLIENTE:
            raise ValidationError("No se puede asignar un lote ya cerrado hacia el cliente")

        taller = self.taller_repo.get_by_id(data.taller_id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")
        if not taller.activo:
            raise ValidationError("El taller seleccionado está inactivo")

        ya_asignado = self.lote_repo.calcular_cantidad_asignada(lote.id, empresa_id)
        disponible = lote.cantidad_total - ya_asignado
        if data.cantidad_asignada > disponible:
            raise ValidationError(
                f"La cantidad excede lo disponible en el lote ({disponible} unidades restantes)"
            )

        asignacion = self.repo.create(
            AsignacionTaller(empresa_id=empresa_id, estado=EstadoAsignacion.ASIGNADO, **data.model_dump())
        )

        if lote.estado == EstadoLote.PENDIENTE_ASIGNACION:
            lote.estado = EstadoLote.ASIGNADO_A_TALLER

        self.db.commit()
        self.db.refresh(asignacion)
        return asignacion

    def obtener(self, id: int, empresa_id: int) -> AsignacionTaller:
        asignacion = self.repo.get_by_id(id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")
        return asignacion

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTaller]:
        return self.repo.listar_por_lote(lote_id, empresa_id)

    def registrar_devolucion(
        self, id: int, empresa_id: int, data: AsignacionTallerRegistrarDevolucion
    ) -> AsignacionTaller:
        asignacion = self.obtener(id, empresa_id)
        if asignacion.estado == EstadoAsignacion.ENTREGADO_COMPLETO:
            raise ValidationError("Esta asignación ya fue marcada como entregada por completo")
        if data.cantidad_devuelta > asignacion.cantidad_asignada:
            raise ValidationError("La cantidad devuelta no puede superar la cantidad asignada")

        asignacion.cantidad_devuelta = data.cantidad_devuelta
        asignacion.fecha_devolucion = data.fecha_devolucion
        asignacion.estado = (
            EstadoAsignacion.ENTREGADO_COMPLETO
            if data.cantidad_devuelta == asignacion.cantidad_asignada
            else EstadoAsignacion.ENTREGADO_PARCIAL
        )

        self._recalcular_estado_lote(asignacion.lote_id, empresa_id)
        self.db.commit()
        self.db.refresh(asignacion)
        return asignacion

    def _recalcular_estado_lote(self, lote_id: int, empresa_id: int) -> None:
        """
        Se ejecuta cada vez que cambia una devolución. Regla:
        - Todas las asignaciones completas -> lote entregado_completo
        - Al menos una completa o parcial -> lote entregado_parcial
        - Ninguna con devolución -> el lote no cambia aquí (sigue en
          pendiente_asignacion o asignado_a_taller según corresponda)
        """
        lote = self.lote_repo.get_by_id(lote_id, empresa_id)
        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        if not asignaciones:
            return

        if all(a.estado == EstadoAsignacion.ENTREGADO_COMPLETO for a in asignaciones):
            lote.estado = EstadoLote.ENTREGADO_COMPLETO
        elif any(
            a.estado in (EstadoAsignacion.ENTREGADO_COMPLETO, EstadoAsignacion.ENTREGADO_PARCIAL)
            for a in asignaciones
        ):
            lote.estado = EstadoLote.ENTREGADO_PARCIAL