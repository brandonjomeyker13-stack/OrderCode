# app/services/asignacion_taller_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoAsignacion, EstadoLote
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.taller_repository import TallerRepository
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
)


def construir_asignacion_out(asignacion: AsignacionTaller, merma: int) -> AsignacionTallerOut:
    """Punto único donde se arma la salida con merma/pendiente -- lo usan
    tanto AsignacionTallerService como IncidenciaService (para anidar la
    asignación dentro de IncidenciaOut), así los dos quedan calculados igual."""
    devuelta = asignacion.cantidad_devuelta or 0
    columnas = {c.name: getattr(asignacion, c.name) for c in asignacion.__table__.columns}
    return AsignacionTallerOut(
        **columnas,
        taller=asignacion.taller,
        cantidad_merma=merma,
        cantidad_pendiente=asignacion.cantidad_asignada - devuelta - merma,
    )


def recalcular_estado_asignacion(asignacion: AsignacionTaller, merma: int) -> None:
    """Las unidades en merma cuentan como "resueltas" igual que las devueltas:
    no se pueden volver a devolver ni quedan como pendientes en el taller."""
    total_resuelto = (asignacion.cantidad_devuelta or 0) + merma
    if total_resuelto >= asignacion.cantidad_asignada:
        asignacion.estado = EstadoAsignacion.ENTREGADO_COMPLETO
    elif total_resuelto > 0:
        asignacion.estado = EstadoAsignacion.ENTREGADO_PARCIAL


class AsignacionTallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)
        self.taller_repo = TallerRepository(db)
        self.incidencia_repo = IncidenciaRepository(db)

    def _con_merma(self, asignacion: AsignacionTaller, empresa_id: int) -> AsignacionTallerOut:
        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        return construir_asignacion_out(asignacion, merma)

    def crear(self, empresa_id: int, data: AsignacionTallerCreate) -> AsignacionTallerOut:
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
        return self._con_merma(asignacion, empresa_id)

    def obtener(self, id: int, empresa_id: int) -> AsignacionTaller:
        asignacion = self.repo.get_by_id(id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")
        return asignacion

    def obtener_con_merma(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        return self._con_merma(self.obtener(id, empresa_id), empresa_id)

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        return [self._con_merma(a, empresa_id) for a in asignaciones]

    def registrar_devolucion(
        self, id: int, empresa_id: int, data: AsignacionTallerRegistrarDevolucion
    ) -> AsignacionTallerOut:
        """`data.cantidad_devuelta` es lo que se devuelve EN ESTE evento (no el
        acumulado). Un taller puede entregar en varias tandas -- se suma sobre
        lo ya devuelto, nunca se sobreescribe (si no, una segunda devolución
        parcial borraría el registro de la primera).

        Las unidades ya registradas como merma (ver IncidenciaService.crear)
        no se pueden devolver -- se descuentan del máximo permitido aquí."""
        asignacion = self.obtener(id, empresa_id)
        if asignacion.estado == EstadoAsignacion.ENTREGADO_COMPLETO:
            raise ValidationError("Esta asignación ya fue marcada como entregada por completo")

        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        nueva_cantidad_devuelta = (asignacion.cantidad_devuelta or 0) + data.cantidad_devuelta
        if nueva_cantidad_devuelta + merma > asignacion.cantidad_asignada:
            pendiente = asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - merma
            raise ValidationError(
                f"La cantidad devuelta excede lo pendiente en la asignación "
                f"({pendiente} unidades, sin contar {merma} en merma)"
            )

        asignacion.cantidad_devuelta = nueva_cantidad_devuelta
        asignacion.fecha_devolucion = data.fecha_devolucion
        recalcular_estado_asignacion(asignacion, merma)

        self._recalcular_estado_lote(asignacion.lote_id, empresa_id)
        self.db.commit()
        self.db.refresh(asignacion)
        return self._con_merma(asignacion, empresa_id)

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
    def listar(self, empresa_id: int, offset: int, limit: int) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.list(empresa_id, offset, limit)
        return [self._con_merma(a, empresa_id) for a in asignaciones]