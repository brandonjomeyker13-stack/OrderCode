# app/services/recepcion/cierre.py
"""Cerrar un conteo: nace la devolución y se mueve el saldo del taller.

Lo usan el cierre automático al completar la proporción y, en lotes viejos,
la aplicación al anotar. Corte ya no confirma: bodega anota y puede deshacer.
No hace commit: quien llama cierra la transacción.
"""
from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.models.asignacion_taller import AsignacionTaller
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.devolucion import Devolucion
from app.models.enums import EstadoConteo, EstadoLote, TipoIncidencia
from app.models.incidencia import Incidencia
from app.repositories.incidencia_repository import IncidenciaRepository
from app.repositories.lote_repository import LoteRepository
from app.services.asignacion_taller_service import (
    AsignacionTallerService,
    recalcular_estado_asignacion,
)


def aplicar_confirmacion(
    db: Session,
    conteo: ConteoRecepcion,
    asignacion: AsignacionTaller,
    empresa_id: int,
    usuario_id: int,
    *,
    ignorar_tope: bool = False,
) -> None:
    """Aplica UN conteo reportado. `asignacion` tiene que ir con lock."""
    if conteo.estado == EstadoConteo.CONFIRMADO:
        raise ValidationError("Este conteo ya estaba confirmado")

    incidencia_repo = IncidenciaRepository(db)
    merma_previa = incidencia_repo.calcular_cantidad_afectada(asignacion.id, empresa_id)
    devuelta_previa = asignacion.cantidad_devuelta or 0
    pendiente = asignacion.cantidad_asignada - devuelta_previa - merma_previa

    if not ignorar_tope and conteo.cantidad_buena + conteo.cantidad_danada > pendiente:
        raise ValidationError(
            f"Bodega contó {conteo.cantidad_buena + conteo.cantidad_danada} unidades y "
            f"del envío solo quedaban {pendiente} pendientes. Habla con bodega para que "
            "revise el conteo antes de confirmar."
        )

    devolucion: Devolucion | None = None
    if conteo.cantidad_buena > 0:
        devolucion = Devolucion(
            empresa_id=empresa_id,
            asignacion_id=asignacion.id,
            cantidad=conteo.cantidad_buena,
            fecha=datetime.combine(conteo.fecha, time.min, tzinfo=timezone.utc),
        )
        db.add(devolucion)
        db.flush()
        asignacion.cantidad_devuelta = devuelta_previa + conteo.cantidad_buena
        asignacion.fecha_devolucion = devolucion.fecha

    merma_total = merma_previa
    if conteo.cantidad_danada > 0:
        db.add(
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
        lote = LoteRepository(db).get_by_id(asignacion.lote_id, empresa_id)
        if lote and lote.estado != EstadoLote.CERRADO_CLIENTE:
            lote.estado = EstadoLote.EN_REVISION_INCIDENCIA

    recalcular_estado_asignacion(asignacion, merma_total)
    AsignacionTallerService(db).recalcular_estado_lote(asignacion.lote_id, empresa_id)

    conteo.estado = EstadoConteo.CONFIRMADO
    conteo.confirmado_por_id = usuario_id
    conteo.confirmado_at = datetime.now(timezone.utc)
    if devolucion is not None:
        conteo.devolucion_id = devolucion.id


def deshacer_aplicacion(
    db: Session,
    conteo: ConteoRecepcion,
    asignacion: AsignacionTaller,
    empresa_id: int,
) -> None:
    """Quita el efecto de un conteo ya aplicado para que bodega pueda corregirlo.

    `asignacion` tiene que ir con lock. No hace commit.
    """
    if conteo.estado != EstadoConteo.CONFIRMADO:
        return

    if conteo.devolucion_id is not None:
        devolucion = db.get(Devolucion, conteo.devolucion_id)
        if devolucion is not None:
            asignacion.cantidad_devuelta = max(
                0, (asignacion.cantidad_devuelta or 0) - devolucion.cantidad
            )
            db.delete(devolucion)
        conteo.devolucion_id = None

    if conteo.cantidad_danada > 0:
        incidencia = db.execute(
            select(Incidencia)
            .where(
                Incidencia.asignacion_id == asignacion.id,
                Incidencia.empresa_id == empresa_id,
                Incidencia.tipo == TipoIncidencia.PRODUCTO_DANADO,
                Incidencia.fecha == conteo.fecha,
                Incidencia.cantidad_afectada == conteo.cantidad_danada,
            )
            .order_by(Incidencia.id.desc())
        ).scalars().first()
        if incidencia is not None:
            db.delete(incidencia)

    conteo.estado = EstadoConteo.REPORTADO
    conteo.confirmado_por_id = None
    conteo.confirmado_at = None
    db.flush()

    merma = IncidenciaRepository(db).calcular_cantidad_afectada(asignacion.id, empresa_id)
    recalcular_estado_asignacion(asignacion, merma)
    AsignacionTallerService(db).recalcular_estado_lote(asignacion.lote_id, empresa_id)


def proporcion_completa(
    conteos: list[ConteoRecepcion], asignacion: AsignacionTaller
) -> bool:
    """Cierra cuando buenas + dañadas de taller cubren lo asignado.

    Arreglo y materia no cuentan: uno sigue pendiente y el otro es una nota.
    """
    cubierto = sum(c.cantidad_buena + c.cantidad_danada for c in conteos)
    return cubierto >= asignacion.cantidad_asignada
