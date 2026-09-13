# app/services/empresa_service.py
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnauthorizedError, ValidationError
from app.core.security import verify_password
from app.models.asignacion_taller import AsignacionTaller
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.color import Color
from app.models.corte import Corte
from app.models.venta import Venta
from app.models.devolucion import Devolucion
from app.models.empresa import Empresa
from app.models.empresa_eliminada import EmpresaEliminada
from app.models.idempotency_key import IdempotencyKey
from app.models.incidencia import Incidencia
from app.models.lote import Lote
from app.models.notificacion import Notificacion
from app.models.notificacion_leida import NotificacionLeida
from app.models.password_reset_token import PasswordResetToken
from app.models.qr_code import QRCode
from app.models.refresh_token import RefreshToken
from app.models.taller import Taller
from app.models.tipo_producto import TipoProducto
from app.models.usuario import Usuario
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

        # Campos enumerados, no copiados de la tabla: `ultima_alerta_at` es
        # una columna interna del programador de alertas y no tiene por qué
        # salir en la respuesta solo porque exista en el modelo.
        return EmpresaConEstadisticas(
            id=empresa.id,
            nombre=empresa.nombre,
            activo=empresa.activo,
            dias_alerta_atraso=empresa.dias_alerta_atraso,
            eliminacion_solicitada_at=empresa.eliminacion_solicitada_at,
            usuario_propietario_id=empresa.usuario_propietario_id,
            created_at=empresa.created_at,
            updated_at=empresa.updated_at,
            total_talleres=self.repo.contar_talleres(empresa_id),
            total_usuarios=self.repo.contar_usuarios(empresa_id),
        )

    # Whitelist explícita en vez de un setattr ciego sobre el schema: `activo`
    # es el interruptor de pago (ver EmpresaUpdate) y no debe volverse
    # escribible por API solo porque alguien agregue el campo al schema.
    _CAMPOS_EDITABLES = {"nombre", "dias_alerta_atraso"}

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

    # --- Derecho de supresión (Ley 1581) ---

    def solicitar_eliminacion(self, empresa_id: int, usuario: Usuario, password: str) -> Empresa:
        """Programa el borrado de toda la cuenta. No borra nada todavía: deja
        una ventana de gracia para que el cliente se arrepienta o exporte sus
        datos (ver purgar_empresas_vencidas).

        Pide la contraseña otra vez a propósito -- es la acción más destructiva
        del sistema y no debe poder dispararse solo por tener una sesión
        abierta en un equipo desatendido."""
        if not verify_password(password, usuario.password_hash):
            raise UnauthorizedError("Contraseña incorrecta")

        empresa = self.repo.get_by_id(empresa_id)
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")
        if empresa.eliminacion_solicitada_at is not None:
            raise ValidationError("La eliminación de esta cuenta ya está programada")

        empresa.eliminacion_solicitada_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(empresa)
        return empresa

    def cancelar_eliminacion(self, empresa_id: int) -> Empresa:
        """Se arrepintieron dentro de la ventana de gracia. Después de la
        purga esto ya no sirve de nada: los datos no se pueden recuperar."""
        empresa = self.repo.get_by_id(empresa_id)
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")
        if empresa.eliminacion_solicitada_at is None:
            raise ValidationError("Esta cuenta no tiene una eliminación programada")

        empresa.eliminacion_solicitada_at = None
        self.db.commit()
        self.db.refresh(empresa)
        return empresa

    # Orden de borrado: de las tablas más dependientes hacia las menos. Se
    # hace explícito en vez de confiar en el ON DELETE CASCADE de `empresas`
    # porque en el camino hay llaves RESTRICT (asignaciones->talleres,
    # lotes->tipos_producto, tipos_producto->qr_codes) que pueden abortar un
    # cascade según cómo las resuelva el motor. Así el resultado es el mismo
    # en Postgres, en SQLite y en los tests.
    # Público porque también lo usa scripts/sembrar_demo.py para rehacer la
    # empresa de demostración. Tenerlo en un solo lugar es lo que garantiza
    # que al agregar una tabla nueva no quede huérfana en ninguno de los dos.
    ORDEN_DE_BORRADO = (
        Notificacion,
        Incidencia,
        # Antes que Devolucion: apunta a ella (devolucion_id) y a usuarios.
        ConteoRecepcion,
        Devolucion,
        AsignacionTaller,
        # Antes que Lote: cuelga de el.
        Venta,
        Lote,
        # Despues de Lote: las lineas le apuntan con RESTRICT, asi que el
        # orden importa o Postgres rechaza el borrado.
        Corte,
        Color,
        TipoProducto,
        QRCode,
        Taller,
        IdempotencyKey,
    )

    def purgar_empresas_vencidas(self) -> list[int]:
        """Borra de verdad las empresas cuya ventana de gracia ya venció.
        Devuelve los ids purgados. Pensado para correrse desde un script
        periódico, no desde una request de usuario (es una operación pesada).
        """
        limite = datetime.now(timezone.utc) - timedelta(
            days=settings.ELIMINACION_CUENTA_DIAS_GRACIA
        )
        vencidas = (
            self.db.execute(
                select(Empresa).where(
                    Empresa.eliminacion_solicitada_at.is_not(None),
                    Empresa.eliminacion_solicitada_at < limite,
                )
            )
            .scalars()
            .all()
        )
        return [self._purgar(empresa) for empresa in vencidas]

    def _purgar(self, empresa: Empresa) -> int:
        empresa_id = empresa.id
        ahora = datetime.now(timezone.utc)

        # El rastro anonimizado se guarda ANTES de borrar, y nunca lleva
        # nombres ni correos (ver EmpresaEliminada).
        self.db.add(
            EmpresaEliminada(
                empresa_id_original=empresa_id,
                fecha_alta=empresa.created_at,
                fecha_solicitud_eliminacion=empresa.eliminacion_solicitada_at,
                fecha_purga=ahora,
            )
        )

        for modelo in self.ORDEN_DE_BORRADO:
            self.db.execute(
                delete(modelo)
                .where(modelo.empresa_id == empresa_id)
                .execution_options(synchronize_session=False)
            )

        # Los tokens cuelgan del usuario, no de la empresa, así que se
        # resuelven por separado antes de poder borrar los usuarios.
        ids_usuarios = select(Usuario.id).where(Usuario.empresa_id == empresa_id)
        for modelo in (RefreshToken, PasswordResetToken, NotificacionLeida):
            self.db.execute(
                delete(modelo)
                .where(modelo.usuario_id.in_(ids_usuarios))
                .execution_options(synchronize_session=False)
            )

        # empresas.usuario_propietario_id apunta a usuarios: hay que soltarlo
        # antes de borrar los usuarios o la FK bloquea el borrado.
        empresa.usuario_propietario_id = None
        self.db.flush()

        self.db.execute(
            delete(Usuario)
            .where(Usuario.empresa_id == empresa_id)
            .execution_options(synchronize_session=False)
        )
        self.db.execute(
            delete(Empresa)
            .where(Empresa.id == empresa_id)
            .execution_options(synchronize_session=False)
        )
        self.db.commit()
        return empresa_id