# app/services/ranking_service.py
"""
El comparativo de talleres de un periodo.

Aquí vive UNA sola vez el cálculo de "qué hizo cada taller": la pantalla y la
exportación a Excel consumen este mismo resultado. Si mañana cambia la
definición de la tasa de merma, cambia en los dos lados a la vez -- que es
justo lo que evita el clásico "el reporte no cuadra con lo que veo en la app".
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.excel import nombre_de_archivo, ranking_a_excel
from app.core.exceptions import ValidationError
from app.core.fechas import fecha_local_de, hoy_local
from app.repositories.empresa_repository import EmpresaRepository
from app.repositories.ranking_repository import RankingRepository
from app.schemas.ranking import RankingTaller, RankingTalleres


class RankingService:
    # Periodo por defecto cuando no se piden fechas. No es "el mes en curso"
    # a propósito: hay empresas que pagan quincenal y ese default les daría un
    # corte que no usan nunca.
    DIAS_POR_DEFECTO = 30

    def __init__(self, db: Session):
        self.db = db
        self.repo = RankingRepository(db)
        self.empresa_repo = EmpresaRepository(db)

    def talleres(
        self,
        empresa_id: int,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> RankingTalleres:
        hasta = hasta or hoy_local()
        desde = desde or hasta - timedelta(days=self.DIAS_POR_DEFECTO - 1)

        if desde > hasta:
            raise ValidationError("La fecha 'desde' no puede ser posterior a 'hasta'")

        devuelto = self.repo.devuelto_por_taller(empresa_id, desde, hasta)
        merma = self.repo.merma_por_taller(empresa_id, desde, hasta)
        asignado = self.repo.asignado_por_taller(empresa_id, desde, hasta)
        tiempos = self.repo.tiempos_de_entrega(empresa_id, desde, hasta)
        pendiente = self.repo.pendiente_por_taller(empresa_id)

        filas = []
        for taller in self.repo.talleres_de(empresa_id):
            unidades_devueltas, entregas = devuelto.get(taller.id, (0, 0))
            unidades_merma = merma.get(taller.id, 0)
            unidades_asignadas = asignado.get(taller.id, 0)
            unidades_pendientes = pendiente.get(taller.id, 0)

            hubo_movimiento = any(
                (unidades_devueltas, unidades_merma, unidades_asignadas, unidades_pendientes)
            )
            # Un taller desactivado que tampoco se movió en el periodo solo
            # alarga la tabla. Si sí se movió, tiene que aparecer: puede que
            # todavía tenga prendas de antes de haberlo desactivado.
            if not taller.activo and not hubo_movimiento:
                continue

            filas.append(
                RankingTaller(
                    taller_id=taller.id,
                    nombre=taller.nombre,
                    numero_taller=taller.numero_taller,
                    activo=taller.activo,
                    unidades_asignadas=unidades_asignadas,
                    unidades_devueltas=unidades_devueltas,
                    unidades_merma=unidades_merma,
                    entregas=entregas,
                    tasa_merma=self._tasa_merma(unidades_devueltas, unidades_merma),
                    dias_promedio_entrega=self._dias_promedio(tiempos.get(taller.id, [])),
                    unidades_pendientes=unidades_pendientes,
                )
            )

        # Quien más entregó, primero. El desempate por pendientes deja arriba
        # al que más carga tiene cuando dos entregaron lo mismo.
        filas.sort(
            key=lambda f: (-f.unidades_devueltas, -f.unidades_pendientes, f.nombre.lower())
        )

        return RankingTalleres(
            desde=desde,
            hasta=hasta,
            talleres=filas,
            total_unidades_devueltas=sum(f.unidades_devueltas for f in filas),
            total_unidades_merma=sum(f.unidades_merma for f in filas),
        )

    def exportar_excel(
        self,
        empresa_id: int,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> tuple[bytes, str]:
        """El MISMO ranking que ve la pantalla, escrito en un .xlsx.

        Reusa `talleres()` en vez de rehacer las consultas: así el archivo no
        puede decir algo distinto a lo que el usuario tiene delante, que es la
        queja clásica contra los reportes exportados.
        """
        ranking = self.talleres(empresa_id, desde=desde, hasta=hasta)
        empresa = self.empresa_repo.get_by_id(empresa_id)
        return ranking_a_excel(ranking, empresa.nombre), nombre_de_archivo(ranking)

    @staticmethod
    def _tasa_merma(devueltas: int, merma: int) -> float:
        """Porcentaje de lo que el taller CERRÓ que salió dañado.

        El denominador es devueltas + merma (lo terminado), no lo asignado: si
        se dividiera entre lo asignado, un taller que apenas empieza un lote
        grande aparecería con una merma bajísima solo por no haber entregado
        todavía.
        """
        terminado = devueltas + merma
        if terminado == 0:
            return 0.0
        return round(merma / terminado * 100, 1)

    @staticmethod
    def _dias_promedio(entregas: list[tuple]) -> float | None:
        if not entregas:
            return None
        dias = [
            # Si la captura quedó mal y la entrega figura antes de la
            # asignación, cuenta como 0. Un promedio negativo se leería como
            # un error del sistema y no como el dato mal digitado que es.
            max((fecha_local_de(entregada_el) - asignada_el).days, 0)
            for entregada_el, asignada_el in entregas
        ]
        return round(sum(dias) / len(dias), 1)
