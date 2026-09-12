"""ventas: sacar del inventario lo que ya esta listo

El ultimo paso del recorrido, que hasta ahora no existia: corte manda al
taller, bodega cuenta lo que vuelve, corte confirma... y ahi se acababa. Las
prendas quedaban "listas" para siempre y el cuarto puesto no tenia nada que
hacer.

`ventas` guarda las salidas. El inventario disponible no se guarda en ninguna
columna: se calcula como lo devuelto y confirmado menos lo vendido. Es a
proposito -- un saldo guardado se desincroniza en cuanto alguien corrige una
devolucion vieja, y este sistema tiene correcciones por todas partes.

No guarda precio. La aplicacion dejo de manejar dinero en c4a83f1e6db0 y eso
no cambia: aqui solo importa que la prenda salio.

Sin enum nativo, asi que el downgrade es limpio: basta con soltar la tabla.

Revision ID: 5690baa95acb
Revises: d61397da4147
"""
import sqlalchemy as sa
from alembic import op


revision = "5690baa95acb"
down_revision = "d61397da4147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ventas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('lote_id', sa.Integer(), nullable=False),
    sa.Column('cantidad', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('nota', sa.Text(), nullable=True),
    sa.Column('registrada_por_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lote_id'], ['lotes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['registrada_por_id'], ['usuarios.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ventas_empresa_id'), 'ventas', ['empresa_id'], unique=False)
    op.create_index(op.f('ix_ventas_fecha'), 'ventas', ['fecha'], unique=False)
    op.create_index(op.f('ix_ventas_lote_id'), 'ventas', ['lote_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ventas_lote_id'), table_name='ventas')
    op.drop_index(op.f('ix_ventas_fecha'), table_name='ventas')
    op.drop_index(op.f('ix_ventas_empresa_id'), table_name='ventas')
    op.drop_table('ventas')
