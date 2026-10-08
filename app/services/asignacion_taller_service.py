# app/services/asignacion_taller_service.py
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.core.pdf import generar_ficha_tecnica
from app.models.asignacion_taller import AsignacionTaller
from app.models.devolucion import Devolucion
from app.models.enums import CanalNotificacion, EstadoAsignacion, EstadoLote
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.repositories.notificacion_repository import NotificacionRepository
from app.repositories.taller_repository import TallerRepository
from app.schemas.asignacion_taller import (
    AsignacionCorteCreate,
    AsignacionTallerCreate,
    AsignacionTallerOut,
    AsignacionTallerRegistrarDevolucion,
    AsignacionTallerUpdate,
    EnvioCorteOut,
)
from app.schemas.filtros import FiltrosAsignacion
from app.services.corte_service import CorteRepository, etiqueta_de
from app.services.notificacion_taller_service import notificar_asignacion

# Identifican la operación ante el registro de Idempotency-Key. Son
# constantes y no literales sueltos porque el valor que se RECLAMA y el que
# se RESUELVE tienen que coincidir exactamente: si se separan, la clave deja
# de reconocerse y la operación se repite.
RUTA_CREAR = "POST /asignaciones"
RUTA_CREAR_CORTE = "POST /asignaciones/por-corte"
RUTA_DEVOLUCION = "POST /asignaciones/{id}/devolucion"


def construir_asignacion_out(
    asignacion: AsignacionTaller,
    merma: int,
    notificado: bool,
    canal: CanalNotificacion | None,
) -> AsignacionTallerOut:
    """Punto único donde se arma la salida con merma/pendiente/notificación
    -- lo usan tanto AsignacionTallerService como IncidenciaService (para
    anidar la asignación dentro de IncidenciaOut), así los dos quedan
    calculados igual."""
    devuelta = asignacion.cantidad_devuelta or 0
    # Los campos van uno por uno a propósito. Antes esto copiaba TODA columna
    # de la tabla con **__table__.columns, y eso significa que cualquier
    # columna que alguien agregue mañana aparece sola en la respuesta sin que
    # nadie lo decida. En este schema eso es grave: `cantidad_asignada` es
    # justo el dato que bodega no puede ver, y una fuga nueva anularía el
    # conteo a ciegas sin que ninguna prueba lo note.
    return AsignacionTallerOut(
        id=asignacion.id,
        empresa_id=asignacion.empresa_id,
        lote_id=asignacion.lote_id,
        cantidad_asignada=asignacion.cantidad_asignada,
        fecha_asignacion=asignacion.fecha_asignacion,
        cantidad_devuelta=asignacion.cantidad_devuelta,
        fecha_devolucion=asignacion.fecha_devolucion,
        estado=asignacion.estado,
        created_at=asignacion.created_at,
        updated_at=asignacion.updated_at,
        taller=asignacion.taller,
        cantidad_merma=merma,
        cantidad_pendiente=asignacion.cantidad_asignada - devuelta - merma,
        notificacion_enviada=notificado,
        canal_notificacion=canal,
        devoluciones=asignacion.devoluciones,
    )


def recalcular_estado_asignacion(asignacion: AsignacionTaller, merma: int) -> None:
    """Las unidades en merma cuentan como "resueltas" igual que las devueltas:
    no se pueden volver a devolver ni quedan como pendientes en el taller."""
    total_resuelto = (asignacion.cantidad_devuelta or 0) + merma
    if total_resuelto >= asignacion.cantidad_asignada:
        asignacion.estado = EstadoAsignacion.ENTREGADO_COMPLETO
    elif total_resuelto > 0:
        asignacion.estado = EstadoAsignacion.ENTREGADO_PARCIAL
    else:
        # Sin nada devuelto ni en merma la asignación está intacta. Hace falta
        # decirlo explícitamente porque ahora un admin puede DESHACER una
        # merma: sin esta rama, borrar la única merma de una asignación la
        # dejaba marcada como "entregado_parcial" sin ninguna entrega detrás.
        asignacion.estado = EstadoAsignacion.ASIGNADO


class AsignacionTallerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AsignacionTallerRepository(db)
        self.lote_repo = LoteRepository(db)
        self.taller_repo = TallerRepository(db)
        self.incidencia_repo = IncidenciaRepository(db)
        self.empresa_repo = EmpresaRepository(db)
        self.notificacion_repo = NotificacionRepository(db)

    def _con_merma(self, asignacion: AsignacionTaller, empresa_id: int) -> AsignacionTallerOut:
        merma = self.incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
        notificado, canal = self.notificacion_repo.resultado(asignacion.id, empresa_id)
        return construir_asignacion_out(asignacion, merma, notificado, canal)

    def _lista_con_merma(
        self, asignaciones: list[AsignacionTaller], empresa_id: int
    ) -> list[AsignacionTallerOut]:
        """Versión en bloque de _con_merma: dos consultas en total en vez de
        dos POR FILA. Con page_size=100 la diferencia es de ~200 consultas a 2."""
        ids = [a.id for a in asignaciones]
        mermas = self.incidencia_repo.merma_por_asignacion(ids, empresa_id)
        notificaciones = self.notificacion_repo.resultado_por_asignacion(ids, empresa_id)
        return [
            construir_asignacion_out(
                a,
                mermas.get(a.id, 0),
                *notificaciones.get(a.id, (False, None)),
            )
            for a in asignaciones
        ]

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
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "asignacion", RUTA_CREAR
        )
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
        cantidad = self._cantidad_a_asignar(lote, data, disponible)

        asignacion = self.repo.create(
            AsignacionTaller(
                empresa_id=empresa_id,
                estado=EstadoAsignacion.ASIGNADO,
                lote_id=data.lote_id,
                taller_id=data.taller_id,
                cantidad_asignada=cantidad,
                fecha_asignacion=data.fecha_asignacion,
            )
        )

        if lote.estado == EstadoLote.PENDIENTE_ASIGNACION:
            lote.estado = EstadoLote.ASIGNADO_A_TALLER

        if not self._confirmar_con_idempotencia(
            empresa_id, idempotency_key, RUTA_CREAR, "asignacion", asignacion.id
        ):
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "asignacion", RUTA_CREAR
            )
            if recurso_id is not None:
                return self.obtener_con_merma(recurso_id, empresa_id)
            raise ValidationError("No se pudo completar la asignación, intenta de nuevo")

        self.db.refresh(asignacion)
        return self._con_merma(asignacion, empresa_id)

    def crear_por_corte(
        self, empresa_id: int, data: AsignacionCorteCreate, idempotency_key: str | None = None
    ) -> EnvioCorteOut:
        """Manda N proporciones completas: todas las prendas y todos los colores.

        20 rojo y 50 verde de una proporción salen juntos al mismo taller.
        Un corte puede mandar una proporción a un taller y la otra a otro.
        """
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "asignacion", RUTA_CREAR_CORTE
        )
        if recurso_id is not None:
            return self._envio_desde(recurso_id, empresa_id)

        if CorteRepository(self.db).obtener(data.corte_id, empresa_id) is None:
            raise NotFoundError("Corte no encontrado")

        taller = self.taller_repo.get_by_id(data.taller_id, empresa_id)
        if taller is None:
            raise NotFoundError("Taller no encontrado")
        if not taller.activo:
            raise ValidationError("El taller seleccionado está inactivo")

        lotes = self.lote_repo.listar_por_corte(data.corte_id, empresa_id, bloquear=True)
        if not lotes:
            raise ValidationError("Este corte no tiene líneas para enviar")
        if any(not lote.es_por_proporciones for lote in lotes):
            raise ValidationError("Este corte no se envía por proporciones completas")

        asignados = self.lote_repo.asignado_por_lote([lote.id for lote in lotes], empresa_id)
        quedan = []
        for lote in lotes:
            disponible = lote.cantidad_total - asignados.get(lote.id, 0)
            quedan.append(disponible // lote.capas_color)
        maximo = min(quedan)
        if maximo <= 0:
            raise ValidationError("No quedan proporciones completas para enviar")
        if data.proporciones > maximo:
            raise ValidationError(
                f"Solo quedan {maximo} proporciones completas en este corte"
            )

        creadas: list[AsignacionTaller] = []
        for lote in lotes:
            asignacion = self.repo.create(
                AsignacionTaller(
                    empresa_id=empresa_id,
                    estado=EstadoAsignacion.ASIGNADO,
                    lote_id=lote.id,
                    taller_id=data.taller_id,
                    cantidad_asignada=data.proporciones * lote.capas_color,
                    fecha_asignacion=data.fecha_asignacion,
                )
            )
            if lote.estado == EstadoLote.PENDIENTE_ASIGNACION:
                lote.estado = EstadoLote.ASIGNADO_A_TALLER
            creadas.append(asignacion)

        if not self._confirmar_con_idempotencia(
            empresa_id, idempotency_key, RUTA_CREAR_CORTE, "asignacion", creadas[0].id
        ):
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "asignacion", RUTA_CREAR_CORTE
            )
            if recurso_id is not None:
                return self._envio_desde(recurso_id, empresa_id)
            raise ValidationError("No se pudo completar la asignación, intenta de nuevo")

        for asignacion in creadas:
            self.db.refresh(asignacion)
        return EnvioCorteOut(
            asignaciones=self._lista_con_merma(creadas, empresa_id),
            unidades=sum(a.cantidad_asignada for a in creadas),
        )

    def _envio_desde(self, asignacion_id: int, empresa_id: int) -> EnvioCorteOut:
        asignacion = self.obtener(asignacion_id, empresa_id)
        hermanas = self._asignaciones_del_mismo_envio(asignacion, empresa_id)
        return EnvioCorteOut(
            asignaciones=self._lista_con_merma(hermanas, empresa_id),
            unidades=sum(a.cantidad_asignada for a in hermanas),
        )

    def _asignaciones_del_mismo_envio(
        self, asignacion: AsignacionTaller, empresa_id: int
    ) -> list[AsignacionTaller]:
        """Las filas que salieron juntas: misma proporción completa del corte."""
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        if lote is None or lote.corte_id is None:
            return [asignacion]
        lineas = self.lote_repo.listar_por_corte(lote.corte_id, empresa_id)
        hermanas = self.repo.listar_envio_corte(
            empresa_id,
            corte_id=lote.corte_id,
            taller_id=asignacion.taller_id,
            fecha=asignacion.fecha_asignacion,
            asignacion_id=asignacion.id,
            lineas_del_corte=len(lineas),
        )
        return hermanas or [asignacion]

    def _cantidad_a_asignar(self, lote, data: AsignacionTallerCreate, disponible: int) -> int:
        """En el flujo nuevo solo salen proporciones enteras.

        Una proporción de leguins negros de 20 capas son 20 unidades, no 19.
        El flujo viejo (sin capas_color) sigue asignando unidades sueltas.
        """
        if lote.es_por_proporciones:
            tamano = lote.capas_color
            if data.proporciones is not None:
                cantidad = data.proporciones * tamano
                if (
                    data.cantidad_asignada is not None
                    and data.cantidad_asignada != cantidad
                ):
                    raise ValidationError(
                        f"Esa proporción son {cantidad} unidades, no {data.cantidad_asignada}"
                    )
            else:
                if data.cantidad_asignada % tamano != 0:
                    raise ValidationError(
                        f"En este corte solo se asignan proporciones enteras "
                        f"({tamano} unidades cada una)"
                    )
                cantidad = data.cantidad_asignada
        else:
            if data.cantidad_asignada is None:
                raise ValidationError("Indica cuántas unidades asignas")
            cantidad = data.cantidad_asignada

        if cantidad > disponible:
            raise ValidationError(
                f"La cantidad excede lo disponible en el lote ({disponible} unidades restantes)"
            )
        return cantidad

    def obtener(self, id: int, empresa_id: int) -> AsignacionTaller:
        asignacion = self.repo.get_by_id(id, empresa_id)
        if asignacion is None:
            raise NotFoundError("Asignación no encontrada")
        return asignacion

    def obtener_con_merma(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        return self._con_merma(self.obtener(id, empresa_id), empresa_id)

    def listar_por_lote(self, lote_id: int, empresa_id: int) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        return self._lista_con_merma(asignaciones, empresa_id)

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
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "asignacion", RUTA_DEVOLUCION
        )
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

        # El evento es la fuente de verdad del historial; los campos de la
        # asignación quedan como acumulado para no tener que sumarlos siempre.
        self.db.add(
            Devolucion(
                empresa_id=empresa_id,
                asignacion_id=asignacion.id,
                cantidad=data.cantidad_devuelta,
                fecha=data.fecha_devolucion,
            )
        )
        asignacion.cantidad_devuelta = nueva_cantidad_devuelta
        asignacion.fecha_devolucion = data.fecha_devolucion
        recalcular_estado_asignacion(asignacion, merma)

        self.recalcular_estado_lote(asignacion.lote_id, empresa_id)

        if not self._confirmar_con_idempotencia(
            empresa_id, idempotency_key, RUTA_DEVOLUCION, "asignacion", asignacion.id
        ):
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "asignacion", RUTA_DEVOLUCION
            )
            if recurso_id is not None:
                return self.obtener_con_merma(recurso_id, empresa_id)
            raise ValidationError("No se pudo registrar la devolución, intenta de nuevo")

        self.db.refresh(asignacion)
        return self._con_merma(asignacion, empresa_id)

    def recalcular_estado_lote(
        self, lote_id: int, empresa_id: int, *, salir_de_revision: bool = False
    ) -> None:
        """
        Se ejecuta cada vez que cambia una devolución. Regla:
        - Todas las asignaciones completas Y el lote entero asignado ->
          entregado_completo
        - Al menos una completa o parcial -> lote entregado_parcial
        - Ninguna con devolución -> el lote no cambia aquí (sigue en
          pendiente_asignacion o asignado_a_taller según corresponda)

        Que el lote esté ENTERO asignado es condición aparte de que las
        asignaciones estén completas, y no una redundancia: de un lote de
        1000 se pueden mandar 100 a un taller y, al devolverlas, esa única
        asignación queda completa mientras 900 unidades no han salido nunca
        de bodega. Sin esta comprobación el lote se daba por entregado con
        el 90% sin producir, y encima quedaba habilitado para cerrarse hacia
        el cliente (`cerrar_hacia_cliente` exige justamente ese estado).
        """
        lote = self.lote_repo.get_by_id(lote_id, empresa_id)

        # Estado terminal: el ciclo con el cliente ya se cerró y ninguna
        # devolución posterior debería reabrirlo por su cuenta.
        if lote.estado == EstadoLote.CERRADO_CLIENTE:
            return

        asignaciones = self.repo.listar_por_lote(lote_id, empresa_id)
        if not asignaciones:
            if salir_de_revision:
                lote.estado = EstadoLote.PENDIENTE_ASIGNACION
            return

        todo_asignado = (
            self.lote_repo.calcular_cantidad_asignada(lote_id, empresa_id) >= lote.cantidad_total
        )
        todas_completas = all(
            a.estado == EstadoAsignacion.ENTREGADO_COMPLETO for a in asignaciones
        )
        hay_entregas = any(
            a.estado in (EstadoAsignacion.ENTREGADO_COMPLETO, EstadoAsignacion.ENTREGADO_PARCIAL)
            for a in asignaciones
        )

        if todo_asignado and todas_completas:
            lote.estado = EstadoLote.ENTREGADO_COMPLETO
        elif lote.estado == EstadoLote.EN_REVISION_INCIDENCIA and not salir_de_revision:
            # La marca de revisión la levanta un admin (`salir_de_revision`),
            # no la devolución de otra asignación del mismo lote: antes
            # cualquier entrega parcial posterior la borraba y la incidencia
            # se perdía de vista, que es justo lo que IncidenciaService.crear
            # dice querer evitar.
            return
        elif hay_entregas:
            lote.estado = EstadoLote.ENTREGADO_PARCIAL
        elif salir_de_revision:
            # Se descartó la única merma y no hay ninguna entrega todavía: el
            # lote simplemente vuelve a estar en manos del taller.
            lote.estado = EstadoLote.ASIGNADO_A_TALLER
    def listar(
        self,
        empresa_id: int,
        offset: int,
        limit: int,
        filtros: FiltrosAsignacion | None = None,
    ) -> list[AsignacionTallerOut]:
        asignaciones = self.repo.list(empresa_id, offset, limit, filtros)
        return self._lista_con_merma(asignaciones, empresa_id)

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

    def ficha_pdf(self, id: int, empresa_id: int) -> bytes:
        """La ficha para imprimir. Ya no se manda por WhatsApp ni correo."""
        asignacion = self.obtener(id, empresa_id)
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        empresa = self.empresa_repo.get_by_id(empresa_id)
        hermanas = self._asignaciones_del_mismo_envio(asignacion, empresa_id)
        lineas = []
        for hermana in hermanas:
            linea = self.lote_repo.get_by_id(hermana.lote_id, empresa_id)
            lineas.append(
                (
                    linea.tipo_producto.nombre,
                    linea.nombre_color,
                    hermana.cantidad_asignada,
                )
            )
        return generar_ficha_tecnica(
            empresa_nombre=empresa.nombre,
            taller_nombre=asignacion.taller.nombre,
            taller_numero=asignacion.taller.numero_taller,
            tipo_producto_nombre=lote.tipo_producto.nombre,
            tipo_producto_referencia=lote.tipo_producto.referencia,
            cantidad_asignada=sum(h.cantidad_asignada for h in hermanas),
            fecha_asignacion=asignacion.fecha_asignacion,
            lote_id=lote.id,
            asignacion_id=asignacion.id,
            corte=etiqueta_de(lote.corte) if lote.corte else None,
            color=lote.nombre_color if len(hermanas) == 1 else None,
            lineas=lineas if len(lineas) > 1 else None,
        )

    def reenviar_notificacion(self, id: int, empresa_id: int) -> AsignacionTallerOut:
        """Reintenta manualmente el envío de la ficha técnica -- útil si
        falló la primera vez (credenciales mal puestas, teléfono incorrecto
        ya corregido, etc.) o si la asignación se creó antes de configurar
        WhatsApp por primera vez."""
        asignacion = self.obtener(id, empresa_id)
        lote = self.lote_repo.get_by_id(asignacion.lote_id, empresa_id)
        empresa = self.empresa_repo.get_by_id(empresa_id)
        notificar_asignacion(
            self.db, empresa_id, asignacion, lote, asignacion.taller, empresa.nombre
        )
        return self._con_merma(asignacion, empresa_id)