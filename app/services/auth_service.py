# app/services/auth_service.py
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.schemas.auth import LoginRequest, RegistroRequest
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.refresh_token import RefreshToken
from app.models.usuario import Usuario
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.auth import LoginRequest
from app.schemas.empresa import EmpresaCreate
from app.schemas.usuario import UsuarioCreate


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.empresa_repo = EmpresaRepository(db)
        self.usuario_repo = UsuarioRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    def registrar_empresa_y_admin(self, data: RegistroRequest) -> Usuario:
        """Alta inicial de un tenant: crea la empresa y su primer usuario
        (admin) en una sola transacción atómica."""
        if self.usuario_repo.get_by_email(data.email) is not None:
            raise ConflictError("Ya existe un usuario con ese email")

        empresa = self.empresa_repo.create(Empresa(nombre=data.nombre_empresa))

        usuario = self.usuario_repo.create(
            Usuario(
                empresa_id=empresa.id,
                nombre=data.nombre,
                email=data.email,
                password_hash=hash_password(data.password),
                rol=RolUsuario.ADMIN,
            )
        )

        empresa.usuario_propietario_id = usuario.id
        self.db.commit()
        self.db.refresh(usuario)
        return usuario

    def autenticar(self, credentials: LoginRequest) -> Usuario:
        usuario = self.usuario_repo.get_by_email(credentials.email)
        # Mensaje idéntico si el email no existe o si la contraseña es
        # incorrecta -- evita que un atacante use el login para enumerar
        # qué emails están registrados.
        if usuario is None or not usuario.activo:
            raise UnauthorizedError("Credenciales inválidas")
        if not verify_password(credentials.password, usuario.password_hash):
            raise UnauthorizedError("Credenciales inválidas")
        return usuario

    def emitir_tokens(self, usuario: Usuario, ip: str | None, user_agent: str | None) -> tuple[str, str]:
        access_token = create_access_token(
            subject=str(usuario.id), empresa_id=usuario.empresa_id, rol=usuario.rol.value
        )

        raw_refresh = generate_refresh_token()
        self.refresh_repo.create(
            RefreshToken(
                usuario_id=usuario.id,
                token_hash=hash_token(raw_refresh),
                expires_at=datetime.now(timezone.utc) + timedelta(days=Settings().REFRESH_TOKEN_EXPIRE_DAYS),
                ip_origen=ip,
                user_agent=user_agent,
            )
        )
        self.db.commit()
        return access_token, raw_refresh

    def refrescar_access_token(self, raw_refresh_token: str) -> tuple[str, Usuario]:
        token = self.refresh_repo.get_by_hash(hash_token(raw_refresh_token))
        if token is None or not self.refresh_repo.es_valido(token):
            raise UnauthorizedError("Sesión inválida o expirada, inicia sesión de nuevo")

        usuario = self.db.get(Usuario, token.usuario_id)
        if usuario is None or not usuario.activo:
            raise UnauthorizedError("Usuario no válido")

        access_token = create_access_token(
            subject=str(usuario.id), empresa_id=usuario.empresa_id, rol=usuario.rol.value
        )
        return access_token, usuario

    def cerrar_sesion(self, raw_refresh_token: str) -> None:
        self.refresh_repo.revocar(hash_token(raw_refresh_token))
        self.db.commit()