# app/services/recepcion/bodega.py
"""Lo que hace quien cuenta: anotar lo que llegó y corregirse."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.asignacion_taller import AsignacionTaller
from app.models.conteo_recepcion import ConteoRecepcion
from app.models.enums import EstadoAsignacion, EstadoConteo
from app.repositories.asignacion_taller_repository import AsignacionTallerRepository
from app.repositories.conteo_recepcion_repository import ConteoRecepcionRepository
from app.schemas.recepcion import (
    ConteoBodegaOut,
    ConteoCreate,
    ConteoUpdate,
    PendienteDeRecibirOut,
)
from app.schemas.taller import TallerOut

#: Identifica la operación ante el registro de Idempotency-Key. Es un
#: identificador opaco, no una URL: si la ruta cambia, este literal NO debe
#: cambiar o las claves ya emitidas dejan de reconocerse.
RUTA_CONTEO = "POST /recepcion/conteos"


def construir_conteo_bodega(conteo: ConteoRecepcion) -> ConteoBodegaOut:
    """Único sitio donde se arma la salida de bodega.

    Los campos van uno por uno y ninguno sale de `cantidad_asignada`. Si
    mañana alguien necesita un dato más aquí, tiene que escribirlo a mano en
    esta función y en el schema, y eso se ve en el diff -- que es exactamente
    lo que tests/test_fugas_de_salida.py existe para forzar.
    """
    asignacion = conteo.asignacion
    return ConteoBodegaOut(
        id=conteo.id,
        asignacion_id=conteo.asignacion_id,
        lote_id=asignacion.lote_id,
        taller=TallerOut.model_validate(asignacion.taller),
        producto=asignacion.lote.tipo_producto.nombre,
        cantidad_buena=conteo.cantidad_buena,
        cantidad_danada=conteo.cantidad_danada,
        fecha=conteo.fecha,
        nota=conteo.nota,
        estado=conteo.estado,
        confirmado_at=conteo.confirmado_at,
        created_at=conteo.created_at,
        updated_at=conteo.updated_at,
    )


class RecepcionBodegaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ConteoRecepcionRepository(db)
        self.asignacion_repo = AsignacionTallerRepository(db)

    # --- Lectura ---

    def listar_pendientes(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[PendienteDeRecibirOut]:
        """Los bultos que todavía están en un taller.

        Devuelve QUÉ puede llegar, nunca CUÁNTO. El filtro es por estado de la
        asignación, no por saldo: preguntar "¿a cuánto le falta?" traería la
        cifra a esta capa y de ahí a una respuesta es un descuido.
        """
        asignaciones = self.asignacion_repo.listar_por_estados(
            empresa_id,
            [EstadoAsignacion.ASIGNADO, EstadoAsignacion.ENTREGADO_PARCIAL],
            offset=offset,
            limit=limit,
        )
        conteos = self.repo.contar_por_asignacion([a.id for a in asignaciones], empresa_id)
        return [
            PendienteDeRecibirOut(
                asignacion_id=a.id,
                lote_id=a.lote_id,
                taller=TallerOut.model_validate(a.taller),
                producto=a.lote.tipo_producto.nombre,
                referencia=a.lote.tipo_producto.referencia,
                fecha_asignacion=a.fecha_asignacion,
                conteos_registrados=conteos.get(a.id, 0),
            )
            for a in asignaciones
        ]

    def listar_conteos(
        self, empresa_id: int, offset: int = 0, limit: int = 50
    ) -> list[ConteoBodegaOut]:
        """Lo que bodega ya anotó, confirmado o no. Su propio cuaderno."""
        conteos = self.repo.list(empresa_id, offset=offset, limit=limit)
        return [construir_conteo_bodega(self._recargar(c, empresa_id)) for c in conteos]

    def obtener(self, id: int, empresa_id: int) -> ConteoBodegaOut:
        return construir_conteo_bodega(self._buscar(id, empresa_id))

    # --- Escritura ---

    def registrar(
        self,
        empresa_id: int,
        data: ConteoCreate,
        usuario_id: int,
        idempotency_key: str | None = None,
    ) -> ConteoBodegaOut:
        """Anota lo que bodega contó. NO lo compara con lo que se envió.

        Esa ausencia es la función entera. Validar aquí obligaría a rechazar
        el conteo que no cuadra, y el rechazo tendría que decir cuál era el
        número bueno -- con lo cual bodega aprendería la cifra que no debe
        saber y le bastaría con teclearla. El descuadre se detecta después,
        cuando corte compara, que es quien sí puede ver las dos cifras.
        """
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "conteo_recepcion", RUTA_CONTEO
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        asignacion = self.asignacion_repo.get_by_id(data.asignacion_id, empresa_id)
        if asignacion is None:
            raise NotFoundError("No encontramos ese envío a taller")

        # Sí se valida la FECHA. No dice nada de cantidades y evita el dedazo
        # más común (el año anterior por costumbre).
        if data.fecha < asignacion.fecha_asignacion:
            raise ValidationError(
                f"La fecha ({data.fecha}) es anterior al día en que el corte salió al "
                f"taller ({asignacion.fecha_asignacion}). Revisa el día."
            )

        conteo = ConteoRecepcion(
            empresa_id=empresa_id,
            asignacion_id=asignacion.id,
            cantidad_buena=data.cantidad_buena,
            cantidad_danada=data.cantidad_danada,
            fecha=data.fecha,
            nota=data.nota,
            estado=EstadoConteo.REPORTADO,
            contado_por_id=usuario_id,
        )
        self.db.add(conteo)
        self.db.flush()

        reclamar_clave(
            self.db, empresa_id, idempotency_key, RUTA_CONTEO, "conteo_recepcion", conteo.id
        )
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "conteo_recepcion", RUTA_CONTEO
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            raise ValidationError("No se pudo guardar el conteo, intenta de nuevo")

        return self.obtener(conteo.id, empresa_id)

    def corregir(self, id: int, empresa_id: int, data: ConteoUpdate) -> ConteoBodegaOut:
        """Bodega vuelve a contar y arregla su propio reporte.

        Solo mientras corte no lo haya confirmado. Después ya movió el saldo
        del taller y el estado del lote: deshacer eso no es una corrección de
        captura, y quien lo haga tiene que ser admin por los endpoints que ya
        existen para eso.
        """
        conteo = self._buscar(id, empresa_id)
        if conteo.estado != EstadoConteo.CONFIRMADO:
            cambios = data.model_dump(exclude_unset=True)
            if not cambios:
                return construir_conteo_bodega(conteo)

            for campo, valor in cambios.items():
                setattr(conteo, campo, valor)

            if conteo.cantidad_buena + conteo.cantidad_danada == 0:
                raise ValidationError(
                    "El conteo quedaría en cero. Si no llegó nada, borra el reporte."
                )
            if conteo.fecha < conteo.asignacion.fecha_asignacion:
                raise ValidationError(
                    f"La fecha ({conteo.fecha}) es anterior al día en que el corte salió "
                    f"al taller ({conteo.asignacion.fecha_asignacion}). Revisa el día."
                )
            self.db.commit()
            return self.obtener(conteo.id, empresa_id)

        raise ValidationError(
            "Este conteo ya lo confirmó corte y no se puede editar. "
            "Si quedó mal, avísale a quien lleva el corte."
        )

    def eliminar(self, id: int, empresa_id: int) -> None:
        """Borra un reporte que nunca debió existir (bulto equivocado)."""
        conteo = self._buscar(id, empresa_id)
        if conteo.estado == EstadoConteo.CONFIRMADO:
            raise ValidationError(
                "Este conteo ya lo confirmó corte y no se puede borrar. "
                "Si quedó mal, avísale a quien lleva el corte."
            )
        self.db.delete(conteo)
        self.db.commit()

    # --- Internos ---

    def _buscar(self, id: int, empresa_id: int) -> ConteoRecepcion:
        conteo = self.repo.obtener_con_contexto(id, empresa_id)
        if conteo is None:
            raise NotFoundError("No encontramos ese conteo")
        return conteo

    def _recargar(self, conteo: ConteoRecepcion, empresa_id: int) -> ConteoRecepcion:
        """`list()` del repositorio genérico no precarga taller ni lote."""
        return self.repo.obtener_con_contexto(conteo.id, empresa_id) or conteo
