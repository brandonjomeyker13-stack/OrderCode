"""tarifa por unidad en producto y asignacion

Cuánto se le paga al taller por unidad. El precio vigente vive en el tipo de
producto (editable), y cada asignación se lleva una COPIA al crearse para que
subir la tarifa no reescriba los cortes ya pagados.

Las dos columnas son NULLABLE y no es negociable: se agregan sobre tablas que
ya tienen filas en producción, y un NOT NULL sin server_default ahí falla al
aplicar la migración. Además el nulo tiene significado propio -- "este trabajo
salió antes de que existieran las tarifas" -- y el ranking lo reporta aparte
en vez de contarlo como gratis.

Revision ID: 18cc41ef807c
Revises: 271aba475a94
Create Date: 2026-08-07 10:35:32.154582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18cc41ef807c'
down_revision: Union[str, None] = '271aba475a94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'asignaciones_taller',
        sa.Column('precio_unitario', sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        'tipos_producto',
        sa.Column('precio_unitario', sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    # Revertir BORRA los precios cargados: no hay de dónde reconstruirlos.
    op.drop_column('tipos_producto', 'precio_unitario')
    op.drop_column('asignaciones_taller', 'precio_unitario')
