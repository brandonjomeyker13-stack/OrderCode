# app/services/asignacion_taller_service.py
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.asignacion_taller import AsignacionTaller
from app.models.enums import EstadoAsignacion, EstadoLote
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.notificacion_whatsapp_repository import NotificacionWhatsappRepository
from app.repositories.taller_repository import TallerRepository
from app.schemas.asignacion_taller import (
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
    AsignacionTallerUpdate,
)
from app.schemas.filtros import FiltrosAsignacion
from app.services.notificacion_taller_service import notificar_asignacion_por_whatsapp


def construir_asignacion_out(
    asignacion: AsignacionTaller, merma: int, notificado: bool
) -> AsignacionTallerOut:
    """Punto único donde se arma la salida con merma/pendiente/notificación
    -- lo usan tanto AsignacionTallerService como IncidenciaService (para
    anidar la asignación dentro de IncidenciaOut), así los dos quedan
    calculados igual."""
    devuelta = asignacion.cantidad_devuelta or 0
    columnas = {c.name: getattr(asignacion, c.name) for c in asignacion.__table__.columns}
    return AsignacionTallerOut(
        **columnas,
        taller=asignacion.taller,
        cantidad_merma=merma,
        cantidad_pendiente=asignacion.cantidad_asignada - devuelta - merma,
        notificacion_whatsapp_enviada=notificado,
    )


def recalcular_estado_asignacion(asignacion: AsignacionTaller, merma: int) -> None:
    """Las unidades en merma cuentan como "resueltas" igual que las devueltas:
    no se pueden volver a devolver ni quedan como pendientes en el taller."""
    total_resuelto = (asignacion.cantidad_devuelta or 0) + merma
    if total_resuelto >= asignacion.cantidad_asignada:
        asignacion.estado = EstadoAsignacion.ENTREGADO_COMPLETO
    elif total_resuelto > 0:
        asignacion.estado = EstadoAsignacion.ENTREGADO_PARCIAL


class AsignacionTallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)
        self.taller_repo = TallerRepository(db)
        self.incidencia_repo = IncidenciaRepository(db)
        self.empresa_repo = EmpresaRepository(db)
        self.notificacion_repo = NotificacionWhatsappRepository(db)

    def _con_merma(self, asignacion: AsignacionTaller, empresa_id: int) -> AsignacionTallerOut:
        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        notificado = self.notificacion_repo.fue_exitosa(asignacion.id, empresa_id)
        return construir_asignacion_out(asignacion, merma, notificado)

    def _es_pristina(self, asignacion: AsignacionTaller, empresa_id: int) -> bool:
        """Sin devolución ni merma registrada -- nada más depende todavía de
        sus cantidades/fechas, así que se puede corregir o borrar sin dejar
        el historial inconsistente."""
        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        return (asignacion.cantidad_devuelta or 0) == 0 and merma == 0

    def _confirmar_con_idempotencia(
        self, empresa_id: int, idempotency_key: str | None, ruta: str, recurso_tipo: str, recurso_id: int
    ) -> bool:
        """Intenta confirmar la transacción ya armada (recurso + clave en el
        mismo commit). Si dos requests con la misma Idempotency-Key llegan a
        la vez, el UNIQUE constraint decide cuál gana -- la que pierde
        descarta su escritura y el caller reusa el resultado de la ganadora
        en vez de fallar con un error 500."""
        reclamar_clave(self.db, empresa_id, idempotency_key, ruta, recurso_tipo, recurso_id)
        try:
            self.db.commit()
            return True
        except IntegrityError:
            self.db.rollback()
            return False

    def crear(
        self, empresa_id: int, data: AsignacionTallerCreate, idempotency_key: str | None = None
    ) -> AsignacionTallerOut:
        recurso_id = resolver_recurso_previo(self.db, empresa_id, idempotency_key, "asignacion")
        if recurso_id is not None:
            return self.obtener_con_merma(recurso_id, empresa_id)

        # Con lock: entre leer lo disponible y confirmar la asignación, otro
        # operario podría asignar el mismo saldo y dejar el lote sobre-asignado.
        lote = self.lote_repo.get_by_id_bloqueando(data.lote_id, empresa_id)
        if lote is None:
            raise NotFoundError("Lote no encontrado")
        if lote.estado == EstadoLote.CERRADO_CLIENTE:
            raise ValidationError("No se puede asignar un lote ya cerrado hacia el cliente")

        taller = self.taller_repo.get_by_id(data.taller_id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")
        if not taller.activo:
            raise ValidationError("El taller seleccionado está inactivo")

        ya_asignado = self.lote_repo.calcular_cantidad_asignada(lote.id, empresa_id)
        disponible = lote.cantidad_total - ya_asignado
        if data.cantidad_asignada > disponible:
            raise ValidationError(
                f"La cantidad excede lo disponible en el lote ({disponible} unidades restantes)"
            )

        asignacion = self.repo.create(
            AsignacionTaller(empresa_id=empresa_id, estado=EstadoAsignacion.ASIGNADO, **data.model_dump())
        )

        if lote.estado == EstadoLote.PENDIENTE_ASIGNACION:
            lote.estado = EstadoLote.ASIGNADO_A_TALLER

        if not self._confirmar_con_idempotencia(
            empresa_id, idempotency_key, "POST /asignaciones", "asignacion", asignacion.id
        ):
            recurso_id = resolver_recurso_previo(self.db, empresa_id, idempotency_key, "asignacion")
            if recurso_id is not None:
                return self.obtener_con_merma(recurso_id, empresa_id)
            raise ValidationError("No se pudo completar la asignación, intenta de nuevo")

        self.db.refresh(asignacion)

        empresa = self.empresa_repo.get_by_id(empresa_id)
        notificar_asignacion_por_whatsapp(self.db, empresa_id, asignacion, lote, taller, empresa.nombre)

        return self._con_merma(asignacion, empresa_id)

    def obtener(self, id: int, empresa_id: int) -> AsignacionTaller:
        asignacion = self.repo.get_by_id(id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")
        return asignacion

    def obtener_con_merma(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        return self._con_merma(self.obtener(id, empresa_id), empresa_id)

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        return [self._con_merma(a, empresa_id) for a in asignaciones]

    def registrar_devolucion(
        self,
        id: int,
        empresa_id: int,
        data: AsignacionTallerRegistrarDevolucion,
        idempotency_key: str | None = None,
    ) -> AsignacionTallerOut:
        """`data.cantidad_devuelta` es lo que se devuelve EN ESTE evento (no el
        acumulado). Un taller puede entregar en varias tandas -- se suma sobre
        lo ya devuelto, nunca se sobreescribe (si no, una segunda devolución
        parcial borraría el registro de la primera).

        Las unidades ya registradas como merma (ver IncidenciaService.crear)
        no se pueden devolver -- se descuentan del máximo permitido aquí."""
        recurso_id = resolver_recurso_previo(self.db, empresa_id, idempotency_key, "asignacion")
        if recurso_id is not None:
            return self.obtener_con_merma(recurso_id, empresa_id)

        # Con lock: dos devoluciones simultáneas leerían el mismo pendiente y
        # ambas pasarían la validación, devolviendo más de lo asignado.
        asignacion = self.repo.get_by_id_bloqueando(id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")
        if asignacion.estado == EstadoAsignacion.ENTREGADO_COMPLETO:
            raise ValidationError("Esta asignación ya fue marcada como entregada por completo")

        fecha_devolucion = data.fecha_devolucion.date()
        if fecha_devolucion < asignacion.fecha_asignacion:
            raise ValidationError(
                f"La fecha de devolución ({fecha_devolucion}) no puede ser anterior a la fecha "
                f"en que se asignó al taller ({asignacion.fecha_asignacion})"
            )
        if asignacion.fecha_devolucion is not None and fecha_devolucion < asignacion.fecha_devolucion.date():
            raise ValidationError(
                f"La fecha de devolución ({fecha_devolucion}) no puede ser anterior a la última "
                f"devolución ya registrada ({asignacion.fecha_devolucion.date()})"
            )

        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        nueva_cantidad_devuelta = (asignacion.cantidad_devuelta or 0) + data.cantidad_devuelta
        if nueva_cantidad_devuelta + merma > asignacion.cantidad_asignada:
            pendiente = asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - merma
            raise ValidationError(
                f"La cantidad devuelta excede lo pendiente en la asignación "
                f"({pendiente} unidades, sin contar {merma} en merma)"
            )

        asignacion.cantidad_devuelta = nueva_cantidad_devuelta
        asignacion.fecha_devolucion = data.fecha_devolucion
        recalcular_estado_asignacion(asignacion, merma)

        self._recalcular_estado_lote(asignacion.lote_id, empresa_id)

        if not self._confirmar_con_idempotencia(
            empresa_id, idempotency_key, "POST /asignaciones/{id}/devolucion", "asignacion", asignacion.id
        ):
            recurso_id = resolver_recurso_previo(self.db, empresa_id, idempotency_key, "asignacion")
            if recurso_id is not None:
                return self.obtener_con_merma(recurso_id, empresa_id)
            raise ValidationError("No se pudo registrar la devolución, intenta de nuevo")

        self.db.refresh(asignacion)
        return self._con_merma(asignacion, empresa_id)

    def _recalcular_estado_lote(self, lote_id: int, empresa_id: int) -> None:
        """
        Se ejecuta cada vez que cambia una devolución. Regla:
        - Todas las asignaciones completas -> lote entregado_completo
        - Al menos una completa o parcial -> lote entregado_parcial
        - Ninguna con devolución -> el lote no cambia aquí (sigue en
          pendiente_asignacion o asignado_a_taller según corresponda)
        """
        lote = self.lote_repo.get_by_id(lote_id, empresa_id)
        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        if not asignaciones:
            return

        if all(a.estado == EstadoAsignacion.ENTREGADO_COMPLETO for a in asignaciones):
            lote.estado = EstadoLote.ENTREGADO_COMPLETO
        elif any(
            a.estado in (EstadoAsignacion.ENTREGADO_COMPLETO, EstadoAsignacion.ENTREGADO_PARCIAL)
            for a in asignaciones
        ):
            lote.estado = EstadoLote.ENTREGADO_PARCIAL
    def listar(
        self,
        empresa_id: int,
        offset: int,
        limit: int,
        filtros: FiltrosAsignacion | None = None,
    ) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.list(empresa_id, offset, limit, filtros)
        return [self._con_merma(a, empresa_id) for a in asignaciones]

    def contar(self, empresa_id: int, filtros: FiltrosAsignacion | None = None) -> int:
        return self.repo.count(empresa_id, filtros)

    def actualizar(
        self, id: int, empresa_id: int, data: AsignacionTallerUpdate
    ) -> AsignacionTallerOut:
        """Corrección de un error de captura -- ver AsignacionTallerUpdate."""
        asignacion = self.obtener(id, empresa_id)
        if not self._es_pristina(asignacion, empresa_id):
            raise ValidationError(
                "No se puede corregir: esta asignación ya tiene devolución o merma registrada"
            )

        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)

        if data.taller_id is not None and data.taller_id != asignacion.taller_id:
            taller = self.taller_repo.get_by_id(data.taller_id, empresa_id)
            if taller is None:
                raise NotFoundError("Taller no encontrado")
            if not taller.activo:
                raise ValidationError("El taller seleccionado está inactivo")
            asignacion.taller_id = data.taller_id

        if data.cantidad_asignada is not None:
            asignado_total = self.lote_repo.calcular_cantidad_asignada(lote.id, empresa_id)
            disponible_sin_esta = lote.cantidad_total - (asignado_total - asignacion.cantidad_asignada)
            if data.cantidad_asignada > disponible_sin_esta:
                raise ValidationError(
                    f"La cantidad excede lo disponible en el lote "
                    f"({disponible_sin_esta} unidades restantes)"
                )
            asignacion.cantidad_asignada = data.cantidad_asignada

        if data.fecha_asignacion is not None:
            if data.fecha_asignacion < lote.fecha_registro:
                raise ValidationError(
                    f"La fecha de asignación ({data.fecha_asignacion}) no puede ser anterior a "
                    f"la fecha de registro del lote ({lote.fecha_registro})"
                )
            asignacion.fecha_asignacion = data.fecha_asignacion

        self.db.commit()
        self.db.refresh(asignacion)
        return self._con_merma(asignacion, empresa_id)

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Borrado físico, solo permitido mientras la asignación sigue
        "pristina". Si el lote se queda sin ninguna asignación, revierte su
        estado a pendiente_asignacion (deshace la transición que hizo `crear`)."""
        asignacion = self.obtener(id, empresa_id)
        if not self._es_pristina(asignacion, empresa_id):
            raise ValidationError(
                "No se puede eliminar: esta asignación ya tiene devolución o merma registrada"
            )

        lote_id = asignacion.lote_id
        self.db.delete(asignacion)
        self.db.flush()

        if not self.repo.listar_por_lote(lote_id, empresa_id):
            lote = self.lote_repo.get_by_id(lote_id, empresa_id)
            if lote and lote.estado == EstadoLote.ASIGNADO_A_TALLER:
                lote.estado = EstadoLote.PENDIENTE_ASIGNACION

        self.db.commit()

    def reenviar_notificacion(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        """Reintenta manualmente el envío de la ficha técnica -- útil si
        falló la primera vez (credenciales mal puestas, teléfono incorrecto
        ya corregido, etc.) o si la asignación se creó antes de configurar
        WhatsApp por primera vez."""
        asignacion = self.obtener(id, empresa_id)
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        empresa = self.empresa_repo.get_by_id(empresa_id)
        notificar_asignacion_por_whatsapp(
            self.db, empresa_id, asignacion, lote, asignacion.taller, empresa.nombre
        )
        return self._con_merma(asignacion, empresa_id)