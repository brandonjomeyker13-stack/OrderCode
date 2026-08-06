# app/services/taller_service.py
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.taller import Taller
from app.repositories.taller_repository import TallerRepository
from app.schemas.taller import TallerCreate, TallerUpdate


class TallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TallerRepository(db)

    # Cuántas veces se reintenta si dos altas simultáneas eligen el mismo
    # número. El UNIQUE de la tabla es quien decide el ganador; la perdedora
    # recalcula y vuelve a intentar en vez de fallarle al usuario.
    _MAX_INTENTOS_NUMERO = 5

    def _siguiente_numero(self, empresa_id: int) -> str:
        """Consecutivo por empresa: el mayor número usado + 1, con ceros a la
        izquierda ("001", "002", ...).

        Solo se consideran los valores puramente numéricos -- si la empresa
        tiene talleres cargados a mano con otro formato ("T-01", "taller A"),
        se ignoran para el conteo en vez de romper la creación."""
        numeros = [
            int(numero)
            for numero in self.repo.numeros_asignados(empresa_id)
            if numero.isdigit()
        ]
        siguiente = max(numeros, default=0) + 1
        return f"{siguiente:03d}"

    def crear(self, empresa_id: int, data: TallerCreate) -> Taller:
        """El número lo asigna el servidor -- ver TallerCreate."""
        for _ in range(self._MAX_INTENTOS_NUMERO):
            taller = Taller(
                empresa_id=empresa_id,
                numero_taller=self._siguiente_numero(empresa_id),
                **data.model_dump(),
            )
            try:
                taller = self.repo.create(taller)
                self.db.commit()
            except IntegrityError:
                # Otra alta simultánea se quedó con ese número: se recalcula.
                self.db.rollback()
                continue
            self.db.refresh(taller)
            return taller

        raise ConflictError(
            "No se pudo asignar un número de taller, intenta de nuevo"
        )

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[Taller]:
        return self.repo.list(empresa_id, offset, limit)

    def contar(self, empresa_id: int) -> int:
        return self.repo.count(empresa_id)

    def obtener(self, id: int, empresa_id: int) -> Taller:
        taller = self.repo.get_by_id(id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")
        return taller

    def actualizar(self, id: int, empresa_id: int, data: TallerUpdate) -> Taller:
        taller = self.obtener(id, empresa_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(taller, field, value)
        self.db.commit()
        self.db.refresh(taller)
        return taller
    def desactivar(self, id: int, empresa_id: int) -> None:
        """Soft-delete: un taller con histórico de asignaciones no se puede
        borrar (RESTRICT en la FK). Se desactiva en vez de eliminarse."""
        taller = self.obtener(id, empresa_id)
        taller.activo = False
        self.db.commit()