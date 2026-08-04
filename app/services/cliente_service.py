# app/services/cliente_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.cliente import Cliente
from app.repositories.cliente_repository import ClienteRepository
from app.schemas.cliente import ClienteCreate, ClienteUpdate


class ClienteService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ClienteRepository(db)

    def crear(self, empresa_id: int, data: ClienteCreate) -> Cliente:
        cliente = self.repo.create(Cliente(empresa_id=empresa_id, **data.model_dump()))
        self.db.commit()
        self.db.refresh(cliente)
        return cliente

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[Cliente]:
        return self.repo.list(empresa_id, offset, limit)

    def obtener(self, id: int, empresa_id: int) -> Cliente:
        cliente = self.repo.get_by_id(id, empresa_id)
        if cliente is None:
            raise NotFoundError("Cliente no encontrado")
        return cliente

    def actualizar(self, id: int, empresa_id: int, data: ClienteUpdate) -> Cliente:
        cliente = self.obtener(id, empresa_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(cliente, field, value)
        self.db.commit()
        self.db.refresh(cliente)
        return cliente
    def desactivar(self, id: int, empresa_id: int) -> None:
        cliente = self.obtener(id, empresa_id)
        cliente.activo = False
        self.db.commit()