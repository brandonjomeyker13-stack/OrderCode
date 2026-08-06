# app/services/resumen_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.repositories.resumen_repository import ResumenRepository
from app.repositories.taller_repository import TallerRepository
from app.schemas.resumen import ResumenGeneral, ResumenTaller


class ResumenService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ResumenRepository(db)
        self.taller_repo = TallerRepository(db)

    def general(self, empresa_id: int) -> ResumenGeneral:
        return ResumenGeneral(
            unidades_en_taller=self.repo.unidades_en_taller(empresa_id),
            unidades_devueltas=self.repo.unidades_devueltas(empresa_id),
            unidades_en_merma=self.repo.unidades_en_merma(empresa_id),
            talleres_activos=self.repo.talleres_activos(empresa_id),
            lotes_pendientes_de_asignar=self.repo.lotes_pendientes_de_asignar(empresa_id),
            asignaciones_abiertas=self.repo.asignaciones_abiertas(empresa_id),
        )

    def por_taller(self, taller_id: int, empresa_id: int) -> ResumenTaller:
        taller = self.taller_repo.get_by_id(taller_id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")

        return ResumenTaller(
            taller=taller,
            unidades_en_taller=self.repo.unidades_en_taller_de(empresa_id, taller_id),
            unidades_devueltas=self.repo.unidades_devueltas_de(empresa_id, taller_id),
            unidades_en_merma=self.repo.unidades_en_merma_de(empresa_id, taller_id),
            asignaciones_abiertas=self.repo.conteo_asignaciones_de(
                empresa_id, taller_id, solo_abiertas=True
            ),
            asignaciones_totales=self.repo.conteo_asignaciones_de(
                empresa_id, taller_id, solo_abiertas=False
            ),
            lotes_en_taller=self.repo.lotes_distintos_en_taller(empresa_id, taller_id),
            total_incidencias=self.repo.total_incidencias_de(empresa_id, taller_id),
        )
