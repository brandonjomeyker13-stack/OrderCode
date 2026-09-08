# app/services/incidencia_service.py
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.fechas import fecha_local_de, rango_utc_del_dia
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.enums import EstadoLote
from app.models.incidencia import Incidencia
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.notificacion_repository import NotificacionRepository
from app.schemas.asignacion_taller import AsignacionTallerOut
from app.schemas.incidencia import IncidenciaCreate, IncidenciaOut, IncidenciaUpdate
from app.services.asignacion_taller_service import (
    AsignacionTallerService,
    construir_asignacion_out,
    recalcular_estado_asignacion,
)

# Ver el comentario de RUTA_CREAR en asignacion_taller_service.
RUTA_CREAR = "POST /incidencias"


class IncidenciaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidenciaRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)
        self.notificacion_repo = NotificacionRepository(db)

    def _con_asignacion(
        self, incidencia: Incidencia, asignacion: AsignacionTaller, merma: int, empresa_id: int
    ) -> IncidenciaOut:
        notificado, canal = self.notificacion_repo.resultado(asignacion.id, empresa_id)
        columnas = {c.name: getattr(incidencia, c.name) for c in incidencia.__table__.columns}
        return IncidenciaOut(
            **columnas,
            asignacion=construir_asignacion_out(asignacion, merma, notificado, canal),
        )

    def crear(self, empresa_id: int, data: IncidenciaCreate, idempotency_key: str | None = None) -> IncidenciaOut:
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "incidencia", RUTA_CREAR
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        # Con lock, igual que al registrar una devolución: la merma compite
        # por el mismo saldo pendiente y dos registros simultáneos podrían
        # superar entre ambos lo que el taller realmente tiene.
        asignacion = self.asignacion_repo.get_by_id_bloqueando(data.asignacion_id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")

        merma_previa = self.repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        pendiente = asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - merma_previa
        if data.cantidad_afectada > pendiente:
            raise ValidationError(
                f"La cantidad afectada excede lo pendiente en la asignación ({pendiente} unidades)"
            )

        incidencia = self.repo.create(Incidencia(empresa_id=empresa_id, **data.model_dump()))

        # Las unidades en merma quedan resueltas igual que una devolución: ya
        # no están "en poder del taller" y no se pueden volver a devolver
        # (ver AsignacionTallerService.registrar_devolucion). Esto NUNCA toca
        # cantidad_asignada, así que no le devuelve stock disponible al lote.
        merma_total = merma_previa + data.cantidad_afectada
        recalcular_estado_asignacion(asignacion, merma_total)

        # Marca el lote para revisión manual -- no se auto-resuelve, un
        # admin debe revisar y decidir el siguiente paso (no queremos
        # que una incidencia se pierda silenciosamente en el flujo).
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        if lote and lote.estado != EstadoLote.CERRADO_CLIENTE:
            lote.estado = EstadoLote.EN_REVISION_INCIDENCIA

        reclamar_clave(self.db, empresa_id, idempotency_key, RUTA_CREAR, "incidencia", incidencia.id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "incidencia", RUTA_CREAR
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            raise ValidationError("No se pudo registrar la incidencia, intenta de nuevo")

        self.db.refresh(incidencia)
        self.db.refresh(asignacion)
        return self._con_asignacion(incidencia, asignacion, merma_total, empresa_id)

    def listar(self, empresa_id: int, offset: int, limit: int) -> list[IncidenciaOut]:
        """Los agregados se cargan en bloque: uno por fila convertía un
        listado de 50 incidencias en más de 100 consultas."""
        incidencias = self.repo.list(empresa_id, offset, limit)
        ids = [i.asignacion_id for i in incidencias]
        mermas = self.repo.merma_por_asignacion(ids, empresa_id)
        notificaciones = self.notificacion_repo.resultado_por_asignacion(ids, empresa_id)

        salida = []
        for incidencia in incidencias:
            notificado, canal = notificaciones.get(incidencia.asignacion_id, (False, None))
            columnas = {
                c.name: getattr(incidencia, c.name) for c in incidencia.__table__.columns
            }
            salida.append(
                IncidenciaOut(
                    **columnas,
                    asignacion=construir_asignacion_out(
                        incidencia.asignacion,
                        mermas.get(incidencia.asignacion_id, 0),
                        notificado,
                        canal,
                    ),
                )
            )
        return salida

    def contar(self, empresa_id: int) -> int:
        return self.repo.count(empresa_id)

    def obtener(self, id: int, empresa_id: int) -> IncidenciaOut:
        incidencia = self._obtener_modelo(id, empresa_id)
        merma = self.repo.calcular_cantidad_afectada(incidencia.asignacion_id, empresa_id)
        return self._con_asignacion(incidencia, incidencia.asignacion, merma, empresa_id)

    # --- Corrección de una merma mal registrada (solo admin) ---
    #
    # Una merma se captura en planta, con prisa y desde el celular:
    # equivocarse de cantidad o de asignación es normal. Sin forma de
    # corregirlo, ese error queda para siempre restando unidades que el taller
    # sí tenía, y deja el lote marcado en revisión sin ninguna salida.

    def _obtener_modelo(self, id: int, empresa_id: int) -> Incidencia:
        incidencia = self.repo.get_by_id(id, empresa_id)
        if incidencia is None:
            raise NotFoundError("Incidencia no encontrada")
        return incidencia

    def _sincronizar(self, asignacion: AsignacionTaller, empresa_id: int) -> int:
        """Deja la asignación y su lote coherentes con la merma que quedó, y
        devuelve esa merma. El lote sale de `en_revision_incidencia` solo
        cuando ya no le queda ninguna merma pendiente de revisar."""
        merma = self.repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        recalcular_estado_asignacion(asignacion, merma)
        AsignacionTallerService(self.db).recalcular_estado_lote(
            asignacion.lote_id,
            empresa_id,
            salir_de_revision=not self.repo.existen_en_lote(asignacion.lote_id, empresa_id),
        )
        return merma

    def actualizar(self, id: int, empresa_id: int, data: IncidenciaUpdate) -> IncidenciaOut:
        incidencia = self._obtener_modelo(id, empresa_id)
        asignacion = incidencia.asignacion

        if data.cantidad_afectada is not None:
            # El tope descuenta las OTRAS mermas de la misma asignación, no
            # todas: si no, corregir 30 a 40 se compararía contra un pendiente
            # que ya tiene descontados esos mismos 30.
            otras = (
                self.repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
                - incidencia.cantidad_afectada
            )
            tope = asignacion.cantidad_asignada - (asignacion.cantidad_devuelta or 0) - otras
            if data.cantidad_afectada > tope:
                raise ValidationError(
                    f"La cantidad afectada no puede pasar de {tope} unidades: es lo que sigue "
                    f"pendiente en la asignación, descontando lo ya devuelto y las otras mermas"
                )
            incidencia.cantidad_afectada = data.cantidad_afectada

        if data.tipo is not None:
            incidencia.tipo = data.tipo
        if data.descripcion is not None:
            incidencia.descripcion = data.descripcion
        if data.fecha is not None:
            incidencia.fecha = data.fecha

        self.db.flush()
        merma = self._sincronizar(asignacion, empresa_id)
        self.db.commit()
        self.db.refresh(incidencia)
        self.db.refresh(asignacion)
        return self._con_asignacion(incidencia, asignacion, merma, empresa_id)

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Descarta una merma que no debió registrarse. Las unidades vuelven a
        contar como pendientes en el taller, que es lo que eran antes del
        error -- NO vuelven al disponible del lote, porque siguen asignadas."""
        incidencia = self._obtener_modelo(id, empresa_id)
        asignacion = incidencia.asignacion

        self.db.delete(incidencia)
        self.db.flush()
        self._sincronizar(asignacion, empresa_id)
        self.db.commit()

    def convertir_en_devolucion(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        """La merma no era tal: el taller sí entregó esas unidades. Se borra la
        incidencia y se registra una devolución por la misma cantidad.

        El saldo de la asignación no se mueve -- esas unidades ya contaban como
        resueltas, solo cambian de columna (de merma a devuelta) -- así que
        esto nunca puede sobrepasar lo asignado. Lo que sí cambia es la plata:
        la merma no se le paga al taller y una entrega sí, y por eso es una
        decisión de admin y no del operario."""
        incidencia = self._obtener_modelo(id, empresa_id)
        asignacion = incidencia.asignacion
        cantidad = incidencia.cantidad_afectada

        # La devolución guarda hora y la incidencia solo día: se ancla al
        # arranque de ese día local para que caiga en la fecha correcta en los
        # cortes diarios ("devueltas hoy", pagos por periodo -- ver core/fechas).
        momento, _ = rango_utc_del_dia(incidencia.fecha)

        self.db.add(
            Devolucion(
                empresa_id=empresa_id,
                asignacion_id=asignacion.id,
                cantidad=cantidad,
                fecha=momento,
            )
        )
        asignacion.cantidad_devuelta = (asignacion.cantidad_devuelta or 0) + cantidad
        # `fecha_devolucion` es la fecha de la ÚLTIMA entrega: solo avanza. Se
        # compara por día local y no por los datetime crudos porque en SQLite
        # vuelven sin zona horaria y no se pueden comparar con uno que sí la
        # tiene.
        if (
            asignacion.fecha_devolucion is None
            or fecha_local_de(asignacion.fecha_devolucion) < incidencia.fecha
        ):
            asignacion.fecha_devolucion = momento

        self.db.delete(incidencia)
        self.db.flush()
        merma = self._sincronizar(asignacion, empresa_id)
        self.db.commit()
        self.db.refresh(asignacion)

        notificado, canal = self.notificacion_repo.resultado(asignacion.id, empresa_id)
        return construir_asignacion_out(asignacion, merma, notificado, canal)