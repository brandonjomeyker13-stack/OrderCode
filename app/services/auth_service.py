# app/services/auth_service.py
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email import enviar_email
from app.core.exceptions import ConflictError, RateLimitedError, UnauthorizedError
from app.core.google_auth import verificar_id_token_google
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.usuario import Usuario
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.password_reset_token_repository import PasswordResetTokenRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.auth import LoginRequest, RegistroRequest


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.empresa_repo = EmpresaRepository(db)
        self.usuario_repo = UsuarioRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)
        self.reset_repo = PasswordResetTokenRepository(db)

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
        if usuario is None or not usuario.activo:
            raise UnauthorizedError("Credenciales inválidas")

        ahora = datetime.now(timezone.utc)
        bloqueado_hasta = usuario.bloqueado_hasta
        if bloqueado_hasta is not None:
            # Algunos backends (ej. SQLite en tests) devuelven el datetime sin
            # tzinfo aunque la columna sea timezone=True -- siempre se escribe
            # en UTC, así que es seguro asumir UTC si viene naive.
            if bloqueado_hasta.tzinfo is None:
                bloqueado_hasta = bloqueado_hasta.replace(tzinfo=timezone.utc)
            if bloqueado_hasta > ahora:
                segundos_restantes = int((bloqueado_hasta - ahora).total_seconds()) + 1
                minutos_restantes = -(-segundos_restantes // 60)  # ceil sin importar float
                raise RateLimitedError(
                    f"Cuenta bloqueada temporalmente por intentos fallidos. "
                    f"Intenta de nuevo en {minutos_restantes} minuto(s).",
                    retry_after_seconds=segundos_restantes,
                )

        if not verify_password(credentials.password, usuario.password_hash):
            usuario.intentos_fallidos += 1
            if usuario.intentos_fallidos >= settings.LOGIN_MAX_INTENTOS:
                usuario.bloqueado_hasta = ahora + timedelta(minutes=settings.LOGIN_BLOQUEO_MINUTOS)
                usuario.intentos_fallidos = 0
            self.db.commit()
            raise UnauthorizedError("Credenciales inválidas")

        if usuario.intentos_fallidos > 0 or usuario.bloqueado_hasta is not None:
            usuario.intentos_fallidos = 0
            usuario.bloqueado_hasta = None
            self.db.commit()

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
                expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                ip_origen=ip,
                user_agent=user_agent,
            )
        )
        # Limpieza oportunista de tokens vencidos/revocados -- así la tabla
        # no crece sin límite, sin necesitar un cron ni un servicio aparte.
        self.refresh_repo.eliminar_vencidos()
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

    def iniciar_recuperacion_password(self, email: str) -> None:
        """Siempre se comporta igual hacia afuera exista o no el correo --
        evita que alguien use este endpoint para enumerar cuentas."""
        usuario = self.usuario_repo.get_by_email(email)
        if usuario is None or not usuario.activo:
            return

        raw_token = generate_refresh_token()
        self.reset_repo.create(
            PasswordResetToken(
                usuario_id=usuario.id,
                token_hash=hash_token(raw_token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
            )
        )
        self.db.commit()

        # rstrip: no importa si FRONTEND_URL viene con o sin "/" al final en
        # la variable de entorno -- nunca queda una doble barra en el link.
        link = f"{settings.FRONTEND_URL.rstrip('/')}/restablecer?token={raw_token}"
        enviar_email(
            usuario.email,
            "Recupera tu contraseña",
            f"""
            <p>Hola {usuario.nombre},</p>
            <p>Recibimos una solicitud para restablecer tu contraseña. Este enlace vence en
            {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutos:</p>
            <p><a href="{link}">Restablecer contraseña</a></p>
            <p>Si no fuiste tú, ignora este correo -- tu contraseña actual sigue siendo válida.</p>
            """,
        )

    def restablecer_password(self, raw_token: str, nueva_password: str) -> None:
        token = self.reset_repo.get_by_hash(hash_token(raw_token))
        if token is None or not self.reset_repo.es_valido(token):
            raise UnauthorizedError("El enlace para restablecer la contraseña es inválido o ya expiró")

        usuario = self.db.get(Usuario, token.usuario_id)
        if usuario is None or not usuario.activo:
            raise UnauthorizedError("Usuario no válido")

        usuario.password_hash = hash_password(nueva_password)
        token.used_at = datetime.now(timezone.utc)
        # Mismo criterio que UsuarioService.cambiar_password: cierra todas
        # las sesiones activas, por si el cambio no lo hizo el dueño real.
        self.refresh_repo.revocar_todos_de_usuario(usuario.id)
        self.db.commit()

        enviar_email(
            usuario.email,
            "Tu contraseña fue cambiada",
            f"""
            <p>Hola {usuario.nombre},</p>
            <p>Tu contraseña se restableció correctamente. Si no fuiste tú, contacta a tu
            administrador de inmediato.</p>
            """,
        )

    def autenticar_con_google(self, id_token: str, nombre_empresa: str | None = None) -> Usuario:
        info = verificar_id_token_google(id_token)
        if not info.get("email_verified", False):
            raise UnauthorizedError("Tu cuenta de Google no tiene el correo verificado")

        email = info["email"]
        usuario = self.usuario_repo.get_by_email(email)

        if usuario is not None:
            if not usuario.activo:
                raise UnauthorizedError("Cuenta inactiva")
            if usuario.google_sub is None:
                usuario.google_sub = info["sub"]
            if not usuario.email_verificado:
                usuario.email_verificado = True
            self.db.commit()
            self.db.refresh(usuario)
            return usuario

        # No existe todavía -- se crea la empresa y su admin en el momento,
        # igual que registrar_empresa_y_admin. NOTA: cuando se agregue cobro,
        # este es el punto donde debería quedar pendiente de pago en vez de
        # activarse de una vez (hoy no hay control de pago, ver conversación).
        nombre = info.get("name") or email
        empresa = self.empresa_repo.create(Empresa(nombre=nombre_empresa or f"Empresa de {nombre}"))
        usuario = self.usuario_repo.create(
            Usuario(
                empresa_id=empresa.id,
                nombre=nombre,
                email=email,
                # Password inutilizable -- esta cuenta solo entra por Google
                # hasta que configure una real (POST /usuarios/me/configurar-password,
                # el front lo detecta con password_configurada=False).
                password_hash=hash_password(generate_refresh_token()),
                rol=RolUsuario.ADMIN,
                google_sub=info["sub"],
                email_verificado=True,
                password_configurada=False,
            )
        )
        empresa.usuario_propietario_id = usuario.id
        self.db.commit()
        self.db.refresh(usuario)
        return usuario