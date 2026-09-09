"""saca la plata del sistema

Decisión del cliente: la aplicación se encarga solo de la gestión de las
prendas -- cuántas salieron, a qué taller fueron, qué volvió y en qué estado.
Lo que se le paga a cada taller lo organizan ellos por fuera.

Con eso desaparece el único dato monetario que existía: el precio de mano de
obra por unidad, que vivía en el tipo de producto y se copiaba congelado a
cada asignación. Y con él desaparecen el monto a pagar del ranking, las
columnas de dinero del Excel y la columna de precio de la plantilla de
importación.

El ranking se queda: unidades entregadas, merma, tasa de calidad, días
promedio y pendientes son gestión de prendas, no contabilidad.

Revision ID: c4a83f1e6db0
Revises: b7d1e9c40a12
"""
from alembic import op
import sqlalchemy as sa


revision = "c4a83f1e6db0"
down_revision = "b7d1e9c40a12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("asignaciones_taller", "precio_unitario")
    op.drop_column("tipos_producto", "precio_unitario")


def downgrade() -> None:
    # Vuelven como nullable, que es como nacieron. Los valores no se pueden
    # recuperar: los borró el upgrade.
    op.add_column(
        "tipos_producto",
        sa.Column("precio_unitario", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "asignaciones_taller",
        sa.Column("precio_unitario", sa.Numeric(precision=12, scale=2), nullable=True),
    )
