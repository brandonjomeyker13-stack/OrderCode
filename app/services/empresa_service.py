# app/services/empresa_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.empresa import Empresa
from app.repositories.empresa_repository import EmpresaRepository
from app.schemas.empresa import EmpresaConEstadisticas, EmpresaUpdate


class EmpresaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = EmpresaRepository(db)

    def obtener_con_estadisticas(self, empresa_id: int) -> EmpresaConEstadisticas:
        empresa = self.repo.get_by_id(empresa_id)
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")

        columnas = {c.name: getattr(empresa, c.name) for c in empresa.__table__.columns}
        return EmpresaConEstadisticas(
            **columnas,
            total_talleres=self.repo.contar_talleres(empresa_id),
            total_usuarios=self.repo.contar_usuarios(empresa_id),
        )

    # Whitelist explícita en vez de un setattr ciego sobre el schema: `activo`
    # es el interruptor de pago (ver EmpresaUpdate) y no debe volverse
    # escribible por API solo porque alguien agregue el campo al schema.
    _CAMPOS_EDITABLES = {"nombre"}

    def actualizar(self, empresa_id: int, data: EmpresaUpdate) -> Empresa:
        empresa = self.repo.get_by_id(empresa_id)
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")
        for field, value in data.model_dump(exclude_unset=True).items():
            if field not in self._CAMPOS_EDITABLES:
                continue
            setattr(empresa, field, value)
        self.db.commit()
        self.db.refresh(empresa)
        return empresa