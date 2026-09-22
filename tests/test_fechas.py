from datetime import date

from app.core.fechas import rango_quincena_sabado


def test_quincena_cierra_sabado_de_por_medio():
    assert rango_quincena_sabado(date(2024, 1, 6)) == (date(2023, 12, 24), date(2024, 1, 6))
    assert rango_quincena_sabado(date(2024, 1, 7)) == (date(2024, 1, 7), date(2024, 1, 20))
    assert rango_quincena_sabado(date(2024, 1, 20), offset=-1) == (
        date(2023, 12, 24),
        date(2024, 1, 6),
    )
