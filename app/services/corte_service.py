# app/services/corte_service.py
"""El tendido: registrarlo entero, con sus líneas."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.idempotencia import reclamar_clave, resolver_recurso_previo
from app.models.color import normalizar
from app.models.corte import Corte
from app.models.corte_color import CorteColor
from app.models.empresa import Empresa
from app.models.enums import EstadoLote
from app.models.lote import Lote
from app.repositories.base import BaseRepository
from app.repositories.tipo_producto_repository import TipoProductoRepository
from app.schemas.corte import (
    ColorDeCorteOut,
    CorteCreate,
    CorteOut,
    CorteUpdate,
    LineaCorteOut,
)
from app.services.color_service import ColorRepository

#: Identificador opaco de la operación ante Idempotency-Key. No es una URL.
RUTA_CREAR = "POST /cortes"

MESES = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


def etiqueta_de(corte: Corte) -> str:
    """Cómo se dice el corte en voz alta: "Corte 07 · 12 sep".

    Lleva la fecha porque el número se repite: el ciclo va de 1 a 100 y vuelve
    a empezar, así que pueden convivir dos corte 07 de meses distintos. Sin la
    fecha, "el 07" es ambiguo justo cuando hay que buscarlo.
    """
    dia = f"{corte.fecha.day} {MESES[corte.fecha.month - 1]}"
    if corte.numero is None:
        return f"Corte · {dia}"
    return f"Corte {corte.numero:02d} · {dia}"


class CorteRepository(BaseRepository[Corte]):
    def __init__(self, db: Session):
        super().__init__(Corte, db)

    def _completo(self):
        return (
            selectinload(Corte.colores),
            selectinload(Corte.lineas).options(
                selectinload(Lote.tipo_producto),
                selectinload(Lote.color),
                selectinload(Lote.asignaciones),
                selectinload(Lote.ventas),
            ),
        )

    def obtener(self, id: int, empresa_id: int) -> Corte | None:
        stmt = (
            select(Corte)
            .where(Corte.id == id, Corte.empresa_id == empresa_id)
            .options(*self._completo())
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def listar(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[Corte]:
        stmt = (
            select(Corte)
            .where(Corte.empresa_id == empresa_id)
            .options(*self._completo())
            # Lo último primero: el corte de hoy es el que se busca.
            .order_by(Corte.fecha.desc(), Corte.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


class CorteService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CorteRepository(db)
        self.color_repo = ColorRepository(db)
        self.tipo_repo = TipoProductoRepository(db)

    # --- Lectura ---

    def listar(self, empresa_id: int, offset: int = 0, limit: int = 50) -> list[CorteOut]:
        return [self._armar(c) for c in self.repo.listar(empresa_id, offset, limit)]

    def obtener(self, id: int, empresa_id: int) -> CorteOut:
        return self._armar(self._buscar(id, empresa_id))

    # --- Escritura ---

    def crear(
        self, empresa_id: int, data: CorteCreate, idempotency_key: str | None = None
    ) -> CorteOut:
        """Registra el tendido entero: cabecera y líneas, en una transacción.

        NO exige que las líneas sumen `cantidad_declarada`. La encargada teclea
        el total antes de desglosar y el desglose puede no cuadrarle; eso no es
        un error de captura que haya que bloquear, es información. La respuesta
        trae la diferencia calculada para que se vea, igual que en la recepción
        se ve la diferencia entre lo enviado y lo contado.
        """
        recurso_id = resolver_recurso_previo(
            self.db, empresa_id, idempotency_key, "corte", RUTA_CREAR
        )
        if recurso_id is not None:
            return self.obtener(recurso_id, empresa_id)

        tipos = self._validar_tipos(empresa_id, data)

        corte = Corte(
            empresa_id=empresa_id,
            numero=self._siguiente_numero(empresa_id, data.fecha),
            fecha=data.fecha,
            cantidad_declarada=data.cantidad_declarada,
            capas=data.capas if data.es_por_capas else None,
        )
        self.db.add(corte)
        self.db.flush()

        if data.es_por_capas:
            self._escribir_por_capas(empresa_id, corte, data, tipos)
        else:
            self._validar_colores(empresa_id, data)
            for linea in data.lineas:
                self.db.add(
                    Lote(
                        empresa_id=empresa_id,
                        corte_id=corte.id,
                        tipo_producto_id=linea.tipo_producto_id,
                        color_id=linea.color_id,
                        proporciones=linea.proporciones,
                        cantidad_total=linea.cantidad,
                        fecha_registro=data.fecha,
                        estado=EstadoLote.PENDIENTE_ASIGNACION,
                    )
                )

        reclamar_clave(self.db, empresa_id, idempotency_key, RUTA_CREAR, "corte", corte.id)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            recurso_id = resolver_recurso_previo(
                self.db, empresa_id, idempotency_key, "corte", RUTA_CREAR
            )
            if recurso_id is not None:
                return self.obtener(recurso_id, empresa_id)
            # El UNIQUE (empresa, numero, fecha) solo puede chocar si el ciclo
            # dio la vuelta entera dentro del mismo día -- 100 cortes en una
            # jornada. Si pasa, es mejor decirlo que inventar otro número.
            raise ConflictError(
                "Ya existe un corte con ese número en esa fecha. Revisa el ciclo de numeración."
            )

        # Los tipos ya validados quedan en memoria para que armar la
        # respuesta no dispare otra consulta por línea.
        del tipos
        return self.obtener(corte.id, empresa_id)

    def actualizar(self, id: int, empresa_id: int, data: CorteUpdate) -> CorteOut:
        corte = self._buscar(id, empresa_id)

        if data.rearma_el_tendido:
            self._rearmar(empresa_id, corte, data)
        else:
            if data.fecha is not None:
                corte.fecha = data.fecha
                for linea in corte.lineas:
                    linea.fecha_registro = data.fecha
            if data.cantidad_declarada is not None:
                corte.cantidad_declarada = data.cantidad_declarada

        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ConflictError(
                "Ya existe un corte con ese número en esa fecha. Revisa el ciclo de numeración."
            )
        return self.obtener(corte.id, empresa_id)

    # --- Internos ---

    def _siguiente_numero(self, empresa_id: int, fecha) -> int:
        """El siguiente del ciclo, con la fila de la empresa bloqueada.

        Sin el lock, dos cortes registrados a la vez leen el mismo contador y
        se llevan el mismo número. Pasa poco y por eso se nota tarde: dos
        cortes con el mismo número y la misma fecha son indistinguibles para
        siempre, y la identidad de un corte es justamente número + fecha.

        El ciclo NO se salta los números que siguen abiertos: un "corte 07" de
        marzo todavía en talleres y otro de septiembre se distinguen por la
        fecha, que para eso está. Lo que sí se salta son los números ya usados
        EN ESA MISMA FECHA, porque ahí la fecha no desempata. Es un caso raro
        -- exige dar la vuelta al ciclo entero en un día -- pero si pasa, sin
        esto el registro reventaba con un error de base de datos que la
        persona no puede resolver.
        """
        empresa = self.db.execute(
            select(Empresa).where(Empresa.id == empresa_id).with_for_update()
        ).scalar_one_or_none()
        if empresa is None:
            raise NotFoundError("Empresa no encontrada")

        usados = set(
            self.db.execute(
                select(Corte.numero).where(
                    Corte.empresa_id == empresa_id,
                    Corte.fecha == fecha,
                    Corte.numero.is_not(None),
                )
            ).scalars()
        )

        siguiente = empresa.corte_ultimo_numero
        for _ in range(empresa.corte_numero_max):
            siguiente += 1
            if siguiente > empresa.corte_numero_max:
                siguiente = 1
            if siguiente not in usados:
                empresa.corte_ultimo_numero = siguiente
                return siguiente

        raise ValidationError(
            f"Ya registraste los {empresa.corte_numero_max} números del ciclo en esta fecha. "
            "Usa otra fecha o amplía el ciclo de la empresa."
        )

    def _rearmar(self, empresa_id: int, corte: Corte, data: CorteUpdate) -> None:
        """Vuelve a armar el tendido. Solo si ninguna línea ha salido a taller.

        Borrar las líneas y los colores y crearlos de nuevo es más seguro que
        intentar parchear cada fila: la cantidad de una línea nueva es
        capas × proporciones, y un ajuste a medias dejaría historia a medias.
        """
        if corte.capas is None:
            raise ValidationError(
                "Este corte es del flujo anterior. No se rearma por capas."
            )
        self._asegurar_que_sigue_virgen(corte)

        tendido = CorteCreate(
            fecha=data.fecha or corte.fecha,
            capas=data.capas,
            colores=data.colores or [],
            prendas=data.prendas or [],
        )
        tipos = self._validar_tipos(empresa_id, tendido)

        for linea in list(corte.lineas):
            self.db.delete(linea)
        corte.colores.clear()
        self.db.flush()

        corte.capas = tendido.capas
        corte.fecha = tendido.fecha
        corte.cantidad_declarada = None
        self._escribir_por_capas(empresa_id, corte, tendido, tipos)

    def _asegurar_que_sigue_virgen(self, corte: Corte) -> None:
        for linea in corte.lineas:
            if (
                linea.estado != EstadoLote.PENDIENTE_ASIGNACION
                or linea.asignaciones
                or linea.ventas
            ):
                raise ValidationError(
                    "Este corte ya salió a un taller. Ya no se puede rearmar el tendido."
                )

    def _escribir_por_capas(
        self, empresa_id: int, corte: Corte, data: CorteCreate, tipos: dict
    ) -> None:
        """Capas × colores × prendas: cada combinación es una línea.

        50 capas, 20 negro + 30 blanco, 2 proporciones de leguins → 40 negro
        y 60 blanco. Eso es el corte, no una cifra que alguien teclee.
        """
        for color in data.colores:
            self.db.add(
                CorteColor(
                    empresa_id=empresa_id,
                    corte_id=corte.id,
                    nombre=color.nombre,
                    nombre_normalizado=normalizar(color.nombre),
                    capas=color.capas,
                )
            )
        for prenda in data.prendas:
            for color in data.colores:
                self.db.add(
                    Lote(
                        empresa_id=empresa_id,
                        corte_id=corte.id,
                        tipo_producto_id=prenda.tipo_producto_id,
                        color_id=None,
                        color_nombre=color.nombre,
                        color_nombre_normalizado=normalizar(color.nombre),
                        capas_color=color.capas,
                        proporciones=prenda.proporciones,
                        cantidad_total=color.capas * prenda.proporciones,
                        fecha_registro=data.fecha,
                        estado=EstadoLote.PENDIENTE_ASIGNACION,
                    )
                )
        if corte.cantidad_declarada is None:
            corte.cantidad_declarada = sum(
                color.capas * prenda.proporciones
                for prenda in data.prendas
                for color in data.colores
            )

    def _validar_tipos(self, empresa_id: int, data: CorteCreate) -> dict:
        """Una consulta para todos los tipos, no una por línea."""
        ids = (
            [prenda.tipo_producto_id for prenda in data.prendas]
            if data.es_por_capas
            else [linea.tipo_producto_id for linea in data.lineas]
        )
        tipos = {}
        for tipo_id in ids:
            if tipo_id in tipos:
                continue
            tipo = self.tipo_repo.get_by_id(tipo_id, empresa_id)
            if tipo is None:
                raise NotFoundError(f"No encontramos el tipo de producto {tipo_id}")
            tipos[tipo.id] = tipo
        return tipos

    def _validar_colores(self, empresa_id: int, data: CorteCreate) -> dict:
        colores = {}
        for linea in data.lineas:
            if linea.color_id is None or linea.color_id in colores:
                continue
            color = self.color_repo.get_by_id(linea.color_id, empresa_id)
            if color is None:
                raise NotFoundError(f"No encontramos el color {linea.color_id}")
            if not color.activo:
                raise ValidationError(
                    f"El color {color.nombre} está desactivado. Actívalo o elige otro."
                )
            colores[color.id] = color
        return colores

    def _buscar(self, id: int, empresa_id: int) -> Corte:
        corte = self.repo.obtener(id, empresa_id)
        if corte is None:
            raise NotFoundError("No encontramos ese corte")
        return corte

    def _armar(self, corte: Corte) -> CorteOut:
        desglosada = corte.cantidad_desglosada
        return CorteOut(
            id=corte.id,
            numero=corte.numero,
            fecha=corte.fecha,
            etiqueta=etiqueta_de(corte),
            cantidad_declarada=corte.cantidad_declarada,
            cantidad_desglosada=desglosada,
            diferencia=(
                corte.cantidad_declarada - desglosada
                if corte.cantidad_declarada is not None
                else None
            ),
            cerrado_at=corte.cerrado_at,
            capas=corte.capas,
            colores=[
                ColorDeCorteOut(nombre=color.nombre, capas=color.capas)
                for color in corte.colores
            ],
            lineas=[
                LineaCorteOut(
                    lote_id=linea.id,
                    tipo_producto_id=linea.tipo_producto_id,
                    producto=linea.tipo_producto.nombre,
                    referencia=linea.tipo_producto.referencia,
                    color=linea.nombre_color,
                    color_hex=linea.color.hex if linea.color else None,
                    cantidad=linea.cantidad_total,
                    proporciones=linea.proporciones,
                    capas_color=linea.capas_color,
                    estado=linea.estado.value,
                )
                for linea in corte.lineas
            ],
            se_puede_editar=self._se_puede_editar(corte),
            created_at=corte.created_at,
            updated_at=corte.updated_at,
        )

    @staticmethod
    def _se_puede_editar(corte: Corte) -> bool:
        if corte.capas is None or not corte.lineas:
            return False
        return all(
            linea.estado == EstadoLote.PENDIENTE_ASIGNACION
            and not linea.asignaciones
            and not linea.ventas
            for linea in corte.lineas
        )
