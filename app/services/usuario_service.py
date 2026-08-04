# app/services/usuario_service.py
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models.usuario import Usuario
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.usuario import CambioPassword, UsuarioCreate, UsuarioUpdate


class UsuarioService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UsuarioRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    def crear(self, empresa_id: int, data: UsuarioCreate) -> Usuario:
        """Solo la usa un admin para invitar a otro usuario a su empresa."""
        if self.repo.get_by_email(data.email) is not None:
            raise ConflictError("Ya existe un usuario con ese email")

        usuario = self.repo.create(
            Usuario(
                empresa_id=empresa_id,
                nombre=data.nombre,
                email=data.email,
                password_hash=hash_password(data.password),
                rol=data.rol,
            )
        )
        self.db.commit()
        self.db.refresh(usuario)
        return usuario

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[Usuario]:
        return self.repo.list(empresa_id, offset, limit)

    def obtener(self, id: int, empresa_id: int) -> Usuario:
        usuario = self.repo.get_by_id(id, empresa_id)
        if usuario is None:
            raise NotFoundError("Usuario no encontrado")
        return usuario

    def actualizar(self, id: int, empresa_id: int, data: UsuarioUpdate) -> Usuario:
        usuario = self.obtener(id, empresa_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(usuario, field, value)
        self.db.commit()
        self.db.refresh(usuario)
        return usuario

    def cambiar_password(self, id: int, empresa_id: int, data: CambioPassword) -> None:
        usuario = self.obtener(id, empresa_id)
        if not verify_password(data.password_actual, usuario.password_hash):
            raise UnauthorizedError("Contraseña actual incorrecta")
        usuario.password_hash = hash_password(data.password_nueva)
        # Invalida todas las sesiones activas -- si alguien más tenía
        # acceso con la contraseña vieja, queda fuera de inmediato.
        self.refresh_repo.revocar_todos_de_usuario(usuario.id)
        self.db.commit()
    def desactivar(self, id: int, empresa_id: int) -> None:
        """Soft-delete: nunca se borra un usuario físicamente (rompería el
        histórico de quién hizo qué). Se desactiva y se cierran sus sesiones."""
        usuario = self.obtener(id, empresa_id)
        usuario.activo = False
        self.refresh_repo.revocar_todos_de_usuario(usuario.id)
        self.db.commit()