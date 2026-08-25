# app/services/alerta_service.py
"""
Detección de lotes atrasados en talleres.

Es la pieza que convierte la app de un registro pasivo ("qué mandé") en algo
que trabaja para el dueño ("qué se me está quedando afuera"). El descontrol de
tiempos es justamente uno de los dolores que el producto promete resolver.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.email import enviar_email
from app.core.exceptions import NotFoundError
from app.core.fechas import hoy_local
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.schemas.alerta import AsignacionAtrasada, ResumenAlertas

logger = logging.getLogger(__name__)

# Margen para no repetir el resumen si el script se corre varias veces el
# mismo día. Menos de 24h para que no se salte un día por correr un poco antes.
HORAS_ENTRE_RESUMENES = 20


class AlertaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AsignacionTallerRepository(db)
        self.incidencia_repo = IncidenciaRepository(db)
        self.empresa_repo = EmpresaRepository(db)

    def resumen(self, empresa_id: int, hoy: date | None = None) -> ResumenAlertas:
        empresa = self.empresa_repo.get_by_id(empresa_id)
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")

        hoy = hoy or hoy_local()
        umbral = empresa.dias_alerta_atraso
        limite = hoy - timedelta(days=umbral)

        asignaciones = self.repo.listar_atrasadas(empresa_id, limite)
        # En bloque, no una consulta por fila (ver el N+1 que ya corregimos
        # en los listados).
        mermas = self.incidencia_repo.merma_por_asignacion(
            [a.id for a in asignaciones], empresa_id
        )

        atrasadas = []
        for asignacion in asignaciones:
            pendiente = (
                asignacion.cantidad_asignada
                - (asignacion.cantidad_devuelta or 0)
                - mermas.get(asignacion.id, 0)
            )
            # Defensa por si el estado quedó desalineado con las cantidades:
            # sin nada pendiente no hay nada que reclamarle al taller.
            if pendiente <= 0:
                continue
            atrasadas.append(
                AsignacionAtrasada(
                    asignacion_id=asignacion.id,
                    lote_id=asignacion.lote_id,
                    taller=asignacion.taller,
                    producto=asignacion.lote.tipo_producto.nombre,
                    referencia=asignacion.lote.tipo_producto.referencia,
                    fecha_asignacion=asignacion.fecha_asignacion,
                    dias_fuera=(hoy - asignacion.fecha_asignacion).days,
                    cantidad_pendiente=pendiente,
                )
            )

        return ResumenAlertas(
            dias_umbral=umbral,
            total_atrasadas=len(atrasadas),
            unidades_comprometidas=sum(a.cantidad_pendiente for a in atrasadas),
            dias_del_mas_atrasado=max((a.dias_fuera for a in atrasadas), default=0),
            atrasadas=atrasadas,
        )

    # --- Resumen diario por correo ---

    def enviar_resumenes_pendientes(self, hoy: date | None = None) -> list[int]:
        """Recorre las empresas activas y le manda a sus admins el resumen de
        atrasos. Devuelve los ids a los que se les envió.

        Salta las que ya recibieron uno hace poco: un aviso que llega tres
        veces al día se vuelve ruido y se deja de leer."""
        ahora = datetime.now(timezone.utc)
        enviados = []

        empresas = (
            self.db.execute(
                select(Empresa).where(
                    Empresa.activo.is_(True),
                    Empresa.eliminacion_solicitada_at.is_(None),
                )
            )
            .scalars()
            .all()
        )

        for empresa in empresas:
            if not self._toca_enviar(empresa, ahora):
                continue

            resumen = self.resumen(empresa.id, hoy)
            if resumen.total_atrasadas == 0:
                # Sin atrasos no se manda nada: un correo diario diciendo
                # "todo bien" entrena a la gente a ignorarlos.
                continue

            destinatarios = self._admins_de(empresa.id)
            if not destinatarios:
                logger.warning("Empresa %s sin admins activos para avisar", empresa.id)
                continue

            entregado = False
            for usuario in destinatarios:
                if enviar_email(
                    usuario.email,
                    f"{resumen.total_atrasadas} lote(s) atrasado(s) en talleres",
                    self._cuerpo(empresa, usuario, resumen),
                ):
                    entregado = True

            if not entregado:
                # Si no salió NI UN correo, la empresa no se marca como
                # avisada: así el siguiente intento reintenta en vez de
                # saltarla durante 20 horas. Antes se marcaba pase lo que
                # pase, y entonces una caída de Resend -- o simplemente la
                # clave sin configurar -- costaba el aviso del día entero
                # sin que nadie se enterara.
                logger.error(
                    "No se pudo avisar a ningún admin de la empresa %s "
                    "(%s atrasos) -- se reintentará en la próxima corrida",
                    empresa.id,
                    resumen.total_atrasadas,
                )
                continue

            empresa.ultima_alerta_at = ahora
            self.db.commit()
            enviados.append(empresa.id)

        return enviados

    def _toca_enviar(self, empresa: Empresa, ahora: datetime) -> bool:
        if empresa.ultima_alerta_at is None:
            return True
        ultima = empresa.ultima_alerta_at
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        return (ahora - ultima) >= timedelta(hours=HORAS_ENTRE_RESUMENES)

    def _admins_de(self, empresa_id: int) -> list[Usuario]:
        stmt = select(Usuario).where(
            Usuario.empresa_id == empresa_id,
            Usuario.rol == RolUsuario.ADMIN,
            Usuario.activo.is_(True),
        )
        return list(self.db.execute(stmt).scalars().all())

    def _cuerpo(self, empresa: Empresa, usuario: Usuario, resumen: ResumenAlertas) -> str:
        filas = "".join(
            f"<tr>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{escape(a.taller.nombre)}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{escape(a.producto)}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>"
            f"{a.cantidad_pendiente}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>"
            f"<strong>{a.dias_fuera}</strong></td>"
            f"</tr>"
            for a in resumen.atrasadas
        )
        return f"""
        <p>Hola {escape(usuario.nombre)},</p>
        <p>Estos lotes llevan más de <strong>{resumen.dias_umbral} días</strong> en talleres
        sin cerrarse. En total son <strong>{resumen.unidades_comprometidas}</strong> unidades
        pendientes de recibir.</p>
        <table style="border-collapse:collapse;font-family:sans-serif;font-size:14px">
          <tr style="background:#f3f4f6">
            <th style="padding:6px 10px;text-align:left">Taller</th>
            <th style="padding:6px 10px;text-align:left">Producto</th>
            <th style="padding:6px 10px;text-align:right">Pendiente</th>
            <th style="padding:6px 10px;text-align:right">Días</th>
          </tr>
          {filas}
        </table>
        <p style="color:#6b7280;font-size:12px">Puedes ajustar a partir de cuántos días se
        considera un atraso desde la configuración de {escape(empresa.nombre)}.</p>
        """
