# app/services/incidencia_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.enums import EstadoLote
from app.models.incidencia import Incidencia
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.schemas.incidencia import IncidenciaCreate


class IncidenciaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidenciaRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)

    def crear(self, empresa_id: int, data: IncidenciaCreate) -> Incidencia:
        asignacion = self.asignacion_repo.get_by_id(data.asignacion_id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")

        incidencia = self.repo.create(Incidencia(empresa_id=empresa_id, **data.model_dump()))

        # Marca el lote para revisión manual -- no se auto-resuelve, un
        # admin debe revisar y decidir el siguiente paso (no queremos
        # que una incidencia se pierda silenciosamente en el flujo).
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        if lote and lote.estado != EstadoLote.CERRADO_CLIENTE:
            lote.estado = EstadoLote.EN_REVISION_INCIDENCIA

        self.db.commit()
        self.db.refresh(incidencia)
        return incidencia

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[Incidencia]:
        return self.repo.list(empresa_id, offset, limit)
    def obtener(self, id: int, empresa_id: int) -> Incidencia:
        incidencia = self.repo.get_by_id(id, empresa_id)
        if incidencia is None:
            raise NotFoundError("Incidencia no encontrada")
        return incidencia