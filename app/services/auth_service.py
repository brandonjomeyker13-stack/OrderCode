# app/services/auth_service.py
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.email import enviar_email
from app.core.exceptions import ConflictError, ForbiddenError, RateLimitedError, UnauthorizedError
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
from app.repositories.idempotency_key_repository import IdempotencyKeyRepository
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

        if not usuario.empresa.activo:
            raise ForbiddenError(
                "El acceso de tu empresa aún no está activo. Contacta al administrador para activarlo."
            )

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
        # Limpieza oportunista de filas que ya no sirven -- así estas tablas
        # no crecen sin límite, sin necesitar un cron ni un servicio aparte.
        self.refresh_repo.eliminar_vencidos()
        IdempotencyKeyRepository(self.db).eliminar_vencidas()
        self.db.commit()
        return access_token, raw_refresh

    def refrescar_access_token(self, raw_refresh_token: str) -> tuple[str, Usuario, str | None]:
        """Rota el refresh token en cada uso (estándar OAuth 2.0 BCP): devuelve
        uno nuevo y marca el anterior como canjeado. El tercer valor es el
        nuevo refresh token para que el endpoint reescriba la cookie, o None
        si esta llamada cayó en la ventana de gracia (ver abajo) y hay que
        dejar la cookie como está.

        Reusar un token ya canjeado se interpreta según cuándo pasa:
        - Dentro de la ventana de gracia -> dos pestañas refrescando a la vez
          o un reintento de red. Se responde normal, sin rotar otra vez.
        - Después de la ventana -> el token quedó en manos de alguien más
          (cookie copiada). Se cierran TODAS las sesiones del usuario, porque
          ya no se puede distinguir al dueño real del atacante.
        """
        token = self.refresh_repo.get_by_hash(hash_token(raw_refresh_token))
        if token is None:
            raise UnauthorizedError("Sesión inválida o expirada, inicia sesión de nuevo")

        ahora = datetime.now(timezone.utc)

        if token.revoked:
            # Un token revocado que reaparece es señal de robo: quien lo tenga
            # guardado no debería poder usarlo nunca más.
            self.refresh_repo.revocar_todos_de_usuario(token.usuario_id)
            self.db.commit()
            raise UnauthorizedError("Sesión inválida o expirada, inicia sesión de nuevo")

        if not self.refresh_repo.es_valido(token):
            raise UnauthorizedError("Sesión inválida o expirada, inicia sesión de nuevo")

        usuario = self.db.get(Usuario, token.usuario_id)
        if usuario is None or not usuario.activo:
            raise UnauthorizedError("Usuario no válido")

        # Este es el camino que usa el desbloqueo por huella del front, así
        # que una empresa pausada tiene que rebotar acá con un mensaje claro
        # y no más adelante con un 403 suelto en cualquier pantalla.
        if not usuario.empresa.activo:
            raise ForbiddenError(
                "El acceso de tu empresa aún no está activo. Contacta al administrador para activarlo."
            )

        access_token = create_access_token(
            subject=str(usuario.id), empresa_id=usuario.empresa_id, rol=usuario.rol.value
        )

        if token.rotated_at is not None:
            rotated_at = token.rotated_at
            if rotated_at.tzinfo is None:
                rotated_at = rotated_at.replace(tzinfo=timezone.utc)
            dentro_de_gracia = (
                ahora - rotated_at
            ).total_seconds() <= settings.REFRESH_TOKEN_GRACIA_SEGUNDOS
            if not dentro_de_gracia:
                self.refresh_repo.revocar_todos_de_usuario(usuario.id)
                self.db.commit()
                raise UnauthorizedError("Sesión inválida o expirada, inicia sesión de nuevo")
            # Carrera entre pestañas: sirve el access token nuevo, pero no se
            # rota otra vez ni se toca la cookie (la ganadora ya la reescribió).
            return access_token, usuario, None

        token.rotated_at = ahora
        nuevo_raw = generate_refresh_token()
        self.refresh_repo.create(
            RefreshToken(
                usuario_id=usuario.id,
                token_hash=hash_token(nuevo_raw),
                # Ventana deslizante: mientras la persona siga entrando, no
                # tiene que volver a escribir la contraseña. El control de
                # pago no depende de esto, sino de empresa.activo (arriba).
                expires_at=ahora + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                ip_origen=token.ip_origen,
                user_agent=token.user_agent,
            )
        )
        self.db.commit()
        return access_token, usuario, nuevo_raw

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
            # Mismo control que en autenticar() -- si no, entrar por Google
            # "funciona" y todo lo demás falla con 403 en la primera llamada
            # real (get_current_usuario sí lo revisa), dando un error confuso.
            if not usuario.empresa.activo:
                raise ForbiddenError(
                    "El acceso de tu empresa aún no está activo. Contacta al administrador para activarlo."
                )
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