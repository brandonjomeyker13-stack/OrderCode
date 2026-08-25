# app/services/centro_notificaciones_service.py
"""
Centro de notificaciones (la campanita).

Los avisos NO se guardan: se calculan al momento a partir del estado real.
Así nunca quedan desactualizados -- un lote atrasado que el taller entrega
deja de aparecer solo, sin que nadie tenga que ir a limpiar nada.

Lo único que se persiste es qué marcó leído cada usuario, con una clave
estable por aviso (ver NotificacionLeida). Eso es lo que hace que el estado
sobreviva a recargar la página y se comparta entre el celular y el computador.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.incidencia import Incidencia
from app.models.notificacion_leida import NotificacionLeida
from app.repositories.notificacion_repository import NotificacionRepository
from app.schemas.centro_notificaciones import Aviso, CentroNotificaciones, TipoAviso
from app.services.alerta_service import AlertaService

# Ventana de las incidencias que se muestran. Más atrás ya es historial, no
# algo que requiera atención hoy.
DIAS_DE_INCIDENCIAS = 7


class CentroNotificacionesService:
    def __init__(self, db: Session):
        self.db = db
        self.alerta_service = AlertaService(db)
        self.notificacion_repo = NotificacionRepository(db)

    def listar(self, empresa_id: int, usuario_id: int) -> CentroNotificaciones:
        avisos = [
            *self._avisos_de_atrasos(empresa_id),
            *self._avisos_de_envios_fallidos(empresa_id),
            *self._avisos_de_incidencias(empresa_id),
        ]

        leidas = self._claves_leidas(usuario_id)
        for aviso in avisos:
            aviso.leida = aviso.id in leidas

        # Lo más reciente primero, que es como se espera leer una campanita.
        avisos.sort(key=lambda a: a.creada_at, reverse=True)

        return CentroNotificaciones(
            total=len(avisos),
            no_leidas=sum(1 for a in avisos if not a.leida),
            avisos=avisos,
        )

    # --- Fuentes de avisos ---

    def _avisos_de_atrasos(self, empresa_id: int) -> list[Aviso]:
        resumen = self.alerta_service.resumen(empresa_id)
        return [
            Aviso(
                id=f"lote_atrasado:asignacion:{a.asignacion_id}",
                tipo=TipoAviso.LOTE_ATRASADO,
                titulo=f"{a.taller.nombre} lleva {a.dias_fuera} días",
                mensaje=(
                    f"{a.cantidad_pendiente} unidades de {a.producto} siguen "
                    f"pendientes desde el {a.fecha_asignacion.strftime('%d/%m/%Y')}."
                ),
                enlace=f"/asignaciones/{a.asignacion_id}",
                leida=False,
                # La fecha del aviso es la de la asignación: así el más viejo
                # (el más urgente) no se pierde al final de la lista.
                creada_at=datetime.combine(
                    a.fecha_asignacion, datetime.min.time(), tzinfo=timezone.utc
                ),
            )
            for a in resumen.atrasadas
        ]

    def _avisos_de_envios_fallidos(self, empresa_id: int) -> list[Aviso]:
        fallidas = self.notificacion_repo.asignaciones_con_ultimo_envio_fallido(empresa_id)
        return [
            Aviso(
                id=f"envio_fallido:asignacion:{n.asignacion_id}",
                tipo=TipoAviso.ENVIO_FALLIDO,
                titulo="No se pudo enviar la ficha técnica",
                mensaje=(
                    f"La ficha de la asignación #{n.asignacion_id} no llegó al taller. "
                    "Puedes reintentar el envío desde el detalle."
                ),
                enlace=f"/asignaciones/{n.asignacion_id}",
                leida=False,
                creada_at=self._con_zona(n.created_at),
            )
            for n in fallidas
        ]

    def _avisos_de_incidencias(self, empresa_id: int) -> list[Aviso]:
        desde = datetime.now(timezone.utc) - timedelta(days=DIAS_DE_INCIDENCIAS)
        incidencias = (
            self.db.execute(
                select(Incidencia)
                .options(selectinload(Incidencia.asignacion))
                .where(Incidencia.empresa_id == empresa_id, Incidencia.created_at >= desde)
                .order_by(Incidencia.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [
            Aviso(
                id=f"incidencia:{i.id}",
                tipo=TipoAviso.INCIDENCIA,
                titulo=f"{i.cantidad_afectada} unidades reportadas como merma",
                mensaje=i.descripcion or "Se registró una incidencia en una asignación.",
                enlace=f"/asignaciones/{i.asignacion_id}",
                leida=False,
                creada_at=self._con_zona(i.created_at),
            )
            for i in incidencias
        ]

    @staticmethod
    def _con_zona(momento: datetime) -> datetime:
        """Algunos backends devuelven el datetime sin tzinfo aunque la columna
        sea timezone=True. Siempre se escribe en UTC, así que es seguro
        asumirlo -- sin esto, ordenar la lista mezclaría aware con naive y
        reventaría."""
        return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)

    # --- Estado de leído ---

    def _claves_leidas(self, usuario_id: int) -> set[str]:
        stmt = select(NotificacionLeida.clave).where(
            NotificacionLeida.usuario_id == usuario_id
        )
        return set(self.db.execute(stmt).scalars().all())

    def marcar_leida(self, empresa_id: int, usuario_id: int, clave: str) -> bool:
        """Marca un aviso como leído. Devuelve si escribió algo.

        Solo acepta claves que correspondan a un aviso que EXISTE ahora mismo
        para este usuario. Sin esa comprobación, la clave era texto libre: un
        cliente con un bucle podía insertar filas ilimitadas en
        `notificaciones_leidas`, y una clave más larga que la columna reventaba
        como 500.

        Una clave desconocida no es un error: el aviso pudo desaparecer entre
        que la pantalla se cargó y el usuario hizo clic (por ejemplo, el taller
        entregó el lote atrasado). Se ignora en silencio y el endpoint sigue
        siendo idempotente.
        """
        if clave in self._claves_leidas(usuario_id):
            return False
        if clave not in {a.id for a in self.listar(empresa_id, usuario_id).avisos}:
            return False

        self.db.add(
            NotificacionLeida(
                usuario_id=usuario_id, clave=clave, leida_at=datetime.now(timezone.utc)
            )
        )
        self.db.commit()
        return True

    def marcar_todas_leidas(self, empresa_id: int, usuario_id: int) -> int:
        """Marca las que existen AHORA. Un aviso que aparezca después seguirá
        sin leer, que es lo esperable."""
        actuales = {a.id for a in self.listar(empresa_id, usuario_id).avisos}
        nuevas = actuales - self._claves_leidas(usuario_id)
        ahora = datetime.now(timezone.utc)

        for clave in nuevas:
            self.db.add(
                NotificacionLeida(usuario_id=usuario_id, clave=clave, leida_at=ahora)
            )
        self.db.commit()
        return len(nuevas)
