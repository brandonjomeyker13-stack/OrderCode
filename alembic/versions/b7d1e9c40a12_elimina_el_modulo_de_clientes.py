"""elimina el modulo de clientes

La tabla nunca tuvo una sola llave foránea entrante: ningún lote, asignación
ni venta apuntaba a un cliente. Era un CRUD huérfano, hecho sobre el supuesto
de que se producía contra pedido. La primera reunión con el cliente aclaró que
se produce para STOCK -- ventas revisa qué hay disponible y lo despacha -- así
que el módulo entero sobra.

Se borra ahora, antes del rediseño del corte, para no arrastrarlo por todas
las etapas siguientes.

Revision ID: b7d1e9c40a12
Revises: 18cc41ef807c
"""
from alembic import op
import sqlalchemy as sa


revision = "b7d1e9c40a12"
down_revision = "18cc41ef807c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f("ix_clientes_empresa_id"), table_name="clientes")
    op.drop_table("clientes")


def downgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=150), nullable=False),
        sa.Column("telefono", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clientes_empresa_id"), "clientes", ["empresa_id"], unique=False
    )
