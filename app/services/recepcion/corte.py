# app/services/recepcion/corte.py
"""Lo que hace quien confirma: comparar contra lo que mandó, y aceptar."""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.devolucion import Devolucion
from app.models.enums import EstadoConteo, EstadoLote, TipoIncidencia
from app.models.incidencia import Incidencia
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.conteo_recepcion_repository import ConteoRecepcionRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.recepcion import ConteoPorConfirmarOut
from app.schemas.taller import TallerOut
from app.services.asignacion_taller_service import (
    AsignacionTallerService,
    recalcular_estado_asignacion,
)

#: Identificador opaco de la operación ante Idempotency-Key. No es una URL:
#: si la ruta cambia, este literal NO cambia.
RUTA_CONFIRMAR = "POST /recepcion/conteos/{id}/confirmar"


class ConfirmacionCorteService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ConteoRecepcionRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)
        self.incidencia_repo = IncidenciaRepository(db)
        self.lote_repo = LoteRepository(db)
        self.usuario_repo = UsuarioRepository(db)

    # --- Lectura ---

    def listar_por_confirmar(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[ConteoPorConfirmarOut]:
        conteos = self.repo.listar_por_estado(
            empresa_id, EstadoConteo.REPORTADO, offset=offset, limit=limit
        )
        return [self._armar(c, empresa_id) for c in conteos]

    def contar_por_confirmar(self, empresa_id: int) -> int:
        return self.repo.contar_por_estado(empresa_id, EstadoConteo.REPORTADO)

    def obtener(self, id: int, empresa_id: int) -> ConteoPorConfirmarOut:
        return self._armar(self._buscar(id, empresa_id), empresa_id)

    # --- Escritura ---

    def confirmar(
        self,
        id: int,
        empresa_id: int,
        usuario_id: int,
        idempotency_key: str | None = None,
    ) -> ConteoPorConfirmarOut:
        """Corte da por bueno lo que contó bodega. Aquí nace la devolución.

        Hasta este punto el conteo no había movido nada: ni el saldo del
        taller, ni el estado de la asignación, ni el del lote. Todo eso pasa
        ahora, de una vez y en una sola transacción, para que no exista un
        instante en que el saldo esté a medio actualizar.
        """
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "conteo_recepcion", RUTA_CONFIRMAR
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        conteo = self._buscar(id, empresa_id)
        if conteo.estado == EstadoConteo.CONFIRMADO:
            raise ValidationError("Este conteo ya estaba confirmado")

        # Con lock, igual que antes: dos confirmaciones simultáneas leerían el
        # mismo saldo y las dos pasarían, devolviendo más de lo que salió.
        asignacion = self.asignacion_repo.get_by_id_bloqueando(conteo.asignacion_id, empresa_id)
        if asignacion is None:
            raise NotFoundError("No encontramos el envío de ese conteo")

        merma_previa = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        devuelta_previa = asignacion.cantidad_devuelta or 0
        pendiente = asignacion.cantidad_asignada - devuelta_previa - merma_previa

        if conteo.cantidad_buena + conteo.cantidad_danada > pendiente:
            # Este mensaje SÍ nombra las cifras, y puede: lo lee corte, que es
            # quien tiene derecho a verlas. Es el descuadre que el producto
            # existe para sacar a la luz, y el texto dice qué hacer con él.
            raise ValidationError(
                f"Bodega contó {conteo.cantidad_buena + conteo.cantidad_danada} unidades y "
                f"del envío solo quedaban {pendiente} pendientes. Habla con bodega para que "
                f"revise el conteo antes de confirmar."
            )

        devolucion: Devolucion | None = None
        if conteo.cantidad_buena > 0:
            devolucion = Devolucion(
                empresa_id=empresa_id,
                asignacion_id=asignacion.id,
                cantidad=conteo.cantidad_buena,
                # La tabla guarda datetime y bodega anota un día. Se fija a
                # medianoche UTC para que dos conteos del mismo día ordenen
                # por id y no por una hora inventada.
                fecha=datetime.combine(conteo.fecha, time.min, tzinfo=timezone.utc),
            )
            self.db.add(devolucion)
            self.db.flush()
            asignacion.cantidad_devuelta = devuelta_previa + conteo.cantidad_buena
            asignacion.fecha_devolucion = devolucion.fecha

        merma_total = merma_previa
        if conteo.cantidad_danada > 0:
            self.db.add(
                Incidencia(
                    empresa_id=empresa_id,
                    asignacion_id=asignacion.id,
                    tipo=TipoIncidencia.PRODUCTO_DANADO,
                    cantidad_afectada=conteo.cantidad_danada,
                    descripcion=conteo.nota,
                    fecha=conteo.fecha,
                )
            )
            merma_total += conteo.cantidad_danada

            # Mismo criterio que IncidenciaService.crear: una merma no se
            # resuelve sola, deja el lote marcado para que alguien lo mire.
            lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
            if lote and lote.estado != EstadoLote.CERRADO_CLIENTE:
                lote.estado = EstadoLote.EN_REVISION_INCIDENCIA

        recalcular_estado_asignacion(asignacion, merma_total)
        AsignacionTallerService(self.db).recalcular_estado_lote(asignacion.lote_id, empresa_id)

        conteo.estado = EstadoConteo.CONFIRMADO
        conteo.confirmado_por_id = usuario_id
        conteo.confirmado_at = datetime.now(timezone.utc)
        if devolucion is not None:
            conteo.devolucion_id = devolucion.id

        reclamar_clave(
            self.db, empresa_id, idempotency_key, RUTA_CONFIRMAR, "conteo_recepcion", conteo.id
        )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "conteo_recepcion", RUTA_CONFIRMAR
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            raise ValidationError("No se pudo confirmar el conteo, intenta de nuevo")

        return self.obtener(conteo.id, empresa_id)

    # --- Internos ---

    def _buscar(self, id: int, empresa_id: int) -> ConteoRecepcion:
        conteo = self.repo.obtener_con_contexto(id, empresa_id)
        if conteo is None:
            raise NotFoundError("No encontramos ese conteo")
        return conteo

    def _armar(self, conteo: ConteoRecepcion, empresa_id: int) -> ConteoPorConfirmarOut:
        asignacion = conteo.asignacion
        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        pendiente = max(
            asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - merma, 0
        )
        contado = conteo.cantidad_buena + conteo.cantidad_danada

        # Si el conteo ya está confirmado, su propio efecto ya está descontado
        # del pendiente: compararlo contra el pendiente de AHORA daría una
        # diferencia falsa. Se compara contra el pendiente de antes.
        referencia = pendiente + contado if conteo.estado == EstadoConteo.CONFIRMADO else pendiente

        return ConteoPorConfirmarOut(
            id=conteo.id,
            asignacion_id=conteo.asignacion_id,
            lote_id=asignacion.lote_id,
            taller=TallerOut.model_validate(asignacion.taller),
            producto=asignacion.lote.tipo_producto.nombre,
            referencia=asignacion.lote.tipo_producto.referencia,
            cantidad_buena=conteo.cantidad_buena,
            cantidad_danada=conteo.cantidad_danada,
            fecha=conteo.fecha,
            nota=conteo.nota,
            estado=conteo.estado,
            cantidad_asignada=asignacion.cantidad_asignada,
            cantidad_pendiente=referencia,
            diferencia=contado - referencia,
            contado_por=self._nombre(conteo.contado_por_id, empresa_id),
            confirmado_por=self._nombre(conteo.confirmado_por_id, empresa_id),
            confirmado_at=conteo.confirmado_at,
            created_at=conteo.created_at,
            updated_at=conteo.updated_at,
        )

    def _nombre(self, usuario_id: int | None, empresa_id: int) -> str | None:
        if usuario_id is None:
            return None
        usuario = self.usuario_repo.get_by_id(usuario_id, empresa_id)
        return usuario.nombre if usuario else None
