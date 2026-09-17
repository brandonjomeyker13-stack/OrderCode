"""capas, colores a mano y quincena

El tendido se registra por capas y colores escritos a mano, no por un
catálogo. De cada color × cada prenda nace una línea cuya cantidad es
capas_color × proporciones. Los cortes viejos (lineas + color_id) no se
tocan: sus lotes siguen sin capas_color y el flujo de confirmación de
corte sigue aplicando ahí.

Bodega clasifica lo que llega en buena / dañada de taller / materia /
arreglo. Materia es nota; arreglo vuelve pendiente al mismo taller.

`empresas.quincena_dias` es el tamaño por defecto del rango al liquidar
talleres. El cuaderno de bodega no se usa más de 30 días.

Revision ID: b8a1c2d3e4f5
Revises: e4f66d4c7582
"""
import sqlalchemy as sa
from alembic import op


revision = "b8a1c2d3e4f5"
down_revision = "e4f66d4c7582"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cortes", sa.Column("capas", sa.Integer(), nullable=True))

    op.create_table(
        "corte_colores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("corte_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=60), nullable=False),
        sa.Column("nombre_normalizado", sa.String(length=60), nullable=False),
        sa.Column("capas", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["corte_id"], ["cortes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte_id", "nombre_normalizado", name="uq_corte_color_nombre"),
    )
    op.create_index(op.f("ix_corte_colores_empresa_id"), "corte_colores", ["empresa_id"])
    op.create_index(op.f("ix_corte_colores_corte_id"), "corte_colores", ["corte_id"])

    with op.batch_alter_table("lotes") as lotes:
        lotes.add_column(sa.Column("color_nombre", sa.String(length=60), nullable=True))
        lotes.add_column(
            sa.Column("color_nombre_normalizado", sa.String(length=60), nullable=True)
        )
        lotes.add_column(sa.Column("capas_color", sa.Integer(), nullable=True))

    with op.batch_alter_table("conteos_recepcion") as conteos:
        conteos.add_column(
            sa.Column(
                "cantidad_danada_materia",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        conteos.add_column(
            sa.Column(
                "cantidad_arreglo",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    op.add_column(
        "empresas",
        sa.Column("quincena_dias", sa.Integer(), nullable=False, server_default="15"),
    )


def downgrade() -> None:
    op.drop_column("empresas", "quincena_dias")
    with op.batch_alter_table("conteos_recepcion") as conteos:
        conteos.drop_column("cantidad_arreglo")
        conteos.drop_column("cantidad_danada_materia")
    with op.batch_alter_table("lotes") as lotes:
        lotes.drop_column("capas_color")
        lotes.drop_column("color_nombre_normalizado")
        lotes.drop_column("color_nombre")
    op.drop_index(op.f("ix_corte_colores_corte_id"), table_name="corte_colores")
    op.drop_index(op.f("ix_corte_colores_empresa_id"), table_name="corte_colores")
    op.drop_table("corte_colores")
    op.drop_column("cortes", "capas")
