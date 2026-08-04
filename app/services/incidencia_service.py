# app/services/incidencia_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoLote
from app.models.incidencia import Incidencia
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.schemas.incidencia import IncidenciaCreate, IncidenciaOut
from app.services.asignacion_taller_service import construir_asignacion_out, recalcular_estado_asignacion


class IncidenciaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidenciaRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)

    def _con_asignacion(
        self, incidencia: Incidencia, asignacion: AsignacionTaller, merma: int
    ) -> IncidenciaOut:
        columnas = {c.name: getattr(incidencia, c.name) for c in incidencia.__table__.columns}
        return IncidenciaOut(**columnas, asignacion=construir_asignacion_out(asignacion, merma))

    def crear(self, empresa_id: int, data: IncidenciaCreate) -> IncidenciaOut:
        asignacion = self.asignacion_repo.get_by_id(data.asignacion_id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")

        merma_previa = self.repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        pendiente = asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - merma_previa
        if data.cantidad_afectada > pendiente:
            raise ValidationError(
                f"La cantidad afectada excede lo pendiente en la asignación ({pendiente} unidades)"
            )

        incidencia = self.repo.create(Incidencia(empresa_id=empresa_id, **data.model_dump()))

        # Las unidades en merma quedan resueltas igual que una devolución: ya
        # no están "en poder del taller" y no se pueden volver a devolver
        # (ver AsignacionTallerService.registrar_devolucion). Esto NUNCA toca
        # cantidad_asignada, así que no le devuelve stock disponible al lote.
        merma_total = merma_previa + data.cantidad_afectada
        recalcular_estado_asignacion(asignacion, merma_total)

        # Marca el lote para revisión manual -- no se auto-resuelve, un
        # admin debe revisar y decidir el siguiente paso (no queremos
        # que una incidencia se pierda silenciosamente en el flujo).
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        if lote and lote.estado != EstadoLote.CERRADO_CLIENTE:
            lote.estado = EstadoLote.EN_REVISION_INCIDENCIA

        self.db.commit()
        self.db.refresh(incidencia)
        self.db.refresh(asignacion)
        return self._con_asignacion(incidencia, asignacion, merma_total)

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[IncidenciaOut]:
        incidencias = self.repo.list(empresa_id, offset, limit)
        return [
            self._con_asignacion(
                i, i.asignacion, self.repo.calcular_cantidad_afectada(i.asignacion_id, empresa_id)
            )
            for i in incidencias
        ]

    def obtener(self, id: int, empresa_id: int) -> IncidenciaOut:
        incidencia = self.repo.get_by_id(id, empresa_id)
        if incidencia is None:
            raise NotFoundError("Incidencia no encontrada")
        merma = self.repo.calcular_cantidad_afectada(incidencia.asignacion_id, empresa_id)
        return self._con_asignacion(incidencia, incidencia.asignacion, merma)