# app/services/tipo_producto_service.py
import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.qr_code import QRCode
from app.models.tipo_producto import TipoProducto
from app.repositories.qr_code_repository import QRCodeRepository
from app.repositories.tipo_producto_repository import TipoProductoRepository
from app.schemas.tipo_producto import TipoProductoCreate, TipoProductoUpdate


class TipoProductoService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TipoProductoRepository(db)
        self.qr_repo = QRCodeRepository(db)

    def crear(self, empresa_id: int, data: TipoProductoCreate) -> TipoProducto:
        qr = self.qr_repo.create(QRCode(empresa_id=empresa_id, token=secrets.token_urlsafe(32)))

        tipo_producto = TipoProducto(empresa_id=empresa_id, qr_code_id=qr.id, **data.model_dump())
        try:
            tipo_producto = self.repo.create(tipo_producto)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError("Ya existe un tipo de producto con esa referencia")
        self.db.refresh(tipo_producto)
        return tipo_producto

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[TipoProducto]:
        return self.repo.list(empresa_id, offset, limit)

    def obtener(self, id: int, empresa_id: int) -> TipoProducto:
        tipo = self.repo.get_by_id(id, empresa_id)
        if tipo is None:
            raise NotFoundError("Tipo de producto no encontrado")
        return tipo

    def obtener_por_qr_token(self, token: str, empresa_id: int) -> TipoProducto:
        """
        NOTA PENDIENTE: hoy exige empresa_id (usuario autenticado). El
        documento de contexto deja abierto si el escaneo del QR debe
        funcionar SIN login para consulta rápida en planta. Si se decide
        eso, este método cambia de firma (buscar por token global, sin
        empresa_id) y hay que resolver cómo evitar enumeración de tokens.
        """
        tipo = self.repo.get_by_qr_token(token, empresa_id)
        if tipo is None:
            raise NotFoundError("QR no válido o inactivo")
        return tipo

    def actualizar(self, id: int, empresa_id: int, data: TipoProductoUpdate) -> TipoProducto:
        tipo = self.obtener(id, empresa_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(tipo, field, value)
        self.db.commit()
        self.db.refresh(tipo)
        return tipo

    def regenerar_qr(self, id: int, empresa_id: int) -> TipoProducto:
        """Revoca el QR físico actual y genera uno nuevo -- útil si se
        pierde o se daña el impreso en planta."""
        tipo = self.obtener(id, empresa_id)
        tipo.qr_code.activo = False

        nuevo_qr = self.qr_repo.create(QRCode(empresa_id=empresa_id, token=secrets.token_urlsafe(32)))
        tipo.qr_code_id = nuevo_qr.id

        self.db.commit()
        self.db.refresh(tipo)
        return tipo
    def eliminar(self, id: int, empresa_id: int) -> None:
        """Borrado físico, pero protegido: si ya existen lotes de este tipo,
        la base de datos rechaza el borrado (ondelete=RESTRICT en Lote) y
        aquí lo traducimos a un mensaje de negocio claro."""
        tipo = self.obtener(id, empresa_id)
        try:
            self.db.delete(tipo)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(
                "No se puede eliminar: este tipo de producto ya tiene lotes registrados"
            )