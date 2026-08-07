# app/services/usuario_service.py
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.core.email import enviar_email
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.core.security import generate_refresh_token, hash_password, verify_password
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.usuario import CambioPassword, ConfigurarPasswordInicial, UsuarioCreate, UsuarioUpdate


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

    def contar(self, empresa_id: int) -> int:
        return self.repo.count(empresa_id)

    def obtener(self, id: int, empresa_id: int) -> Usuario:
        usuario = self.repo.get_by_id(id, empresa_id)
        if usuario is None:
            raise NotFoundError("Usuario no encontrado")
        return usuario

    def actualizar(self, id: int, empresa_id: int, data: UsuarioUpdate) -> Usuario:
        usuario = self.obtener(id, empresa_id)
        cambios = data.model_dump(exclude_unset=True)

        # Este endpoint puede dejar a la empresa sin administradores por dos
        # caminos distintos, y ambos hay que cerrarlos: bajarle el rol al
        # último admin, o desactivarlo. Sin esto, la guardia de `desactivar`
        # y `anonimizar` se puede esquivar con un simple PATCH.
        pierde_el_rol = cambios.get("rol") not in (None, RolUsuario.ADMIN)
        lo_desactivan = cambios.get("activo") is False
        if pierde_el_rol or lo_desactivan:
            self._verificar_que_no_es_el_ultimo_admin(usuario, empresa_id)

        for field, value in cambios.items():
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

        enviar_email(
            usuario.email,
            "Tu contraseña fue cambiada",
            f"""
            <p>Hola {escape(usuario.nombre)},</p>
            <p>Tu contraseña se cambió correctamente. Si no fuiste tú, contacta a tu
            administrador de inmediato.</p>
            """,
        )
    def configurar_password_inicial(
        self, id: int, empresa_id: int, data: ConfigurarPasswordInicial
    ) -> None:
        """Para cuentas creadas por Google Sign-In: ponen su primera
        contraseña real sin necesitar la actual (no existe una que conozcan).
        Por eso solo se permite una vez, mientras password_configurada siga
        en False -- después de esto, corregir la contraseña pasa por
        cambiar_password (con la actual) o el flujo de recuperación."""
        usuario = self.obtener(id, empresa_id)
        if usuario.password_configurada:
            raise ValidationError(
                "Esta cuenta ya tiene una contraseña configurada -- usa 'cambiar contraseña'"
            )
        usuario.password_hash = hash_password(data.password_nueva)
        usuario.password_configurada = True
        self.db.commit()

        enviar_email(
            usuario.email,
            "Configuraste una contraseña para tu cuenta",
            f"""
            <p>Hola {escape(usuario.nombre)},</p>
            <p>Ya puedes iniciar sesión con tu correo y esta contraseña, además de con Google.
            Si no fuiste tú, contacta a tu administrador de inmediato.</p>
            """,
        )

    def _verificar_que_no_es_el_ultimo_admin(self, usuario: Usuario, empresa_id: int) -> None:
        """Sin esta guardia, dar de baja al único admin deja a la empresa sin
        nadie que pueda administrarla -- y en el caso de anonimizar, sin forma
        de recuperarlo."""
        if usuario.rol != RolUsuario.ADMIN or not usuario.activo:
            return
        if self.repo.contar_otros_admins_activos(empresa_id, usuario.id) == 0:
            raise ValidationError(
                "No se puede dar de baja al único administrador activo: "
                "primero asigna el rol de administrador a otro usuario"
            )

    def desactivar(self, id: int, empresa_id: int) -> None:
        """Soft-delete reversible: el usuario deja de entrar pero sus datos se
        conservan (ej. alguien que se fue de la empresa y podría volver). Para
        borrar sus datos personales de verdad, ver `anonimizar`."""
        usuario = self.obtener(id, empresa_id)
        self._verificar_que_no_es_el_ultimo_admin(usuario, empresa_id)
        usuario.activo = False
        self.refresh_repo.revocar_todos_de_usuario(usuario.id)
        self.db.commit()

    def anonimizar(self, id: int, empresa_id: int) -> None:
        """Borra los datos personales del usuario para atender una solicitud
        de supresión (Ley 1581), sin eliminar la fila.

        Se conserva la fila porque otras tablas pueden referenciarla (ej.
        empresas.usuario_propietario_id) y porque el histórico operativo de la
        empresa -- los lotes y asignaciones -- le pertenece a la empresa, no
        a la persona. Lo que desaparece es todo lo que identifica a alguien:
        nombre, correo y su vínculo con la cuenta de Google.

        IRREVERSIBLE: no hay forma de recuperar el nombre ni el correo.
        """
        usuario = self.obtener(id, empresa_id)
        self._verificar_que_no_es_el_ultimo_admin(usuario, empresa_id)

        # El correo tiene UNIQUE: se reemplaza por uno derivado del id (que no
        # dice nada de la persona) en vez de vaciarlo, para no chocar si se
        # anonimiza a más de un usuario. El dominio .invalid está reservado
        # justamente para esto, así nadie puede recibir correo ahí.
        usuario.nombre = "Usuario eliminado"
        usuario.email = f"eliminado-{usuario.id}@anonimizado.invalid"
        usuario.google_sub = None
        usuario.email_verificado = False
        # Contraseña imposible de adivinar y que nadie conoce: la cuenta queda
        # inutilizable incluso si alguien la reactivara por error.
        usuario.password_hash = hash_password(generate_refresh_token())
        usuario.activo = False

        self.refresh_repo.revocar_todos_de_usuario(usuario.id)
        self.db.commit()