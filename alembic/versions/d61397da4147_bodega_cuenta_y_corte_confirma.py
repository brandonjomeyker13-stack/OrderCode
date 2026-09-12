"""bodega cuenta y corte confirma

La tabla donde vive lo que bodega contó ANTES de que nadie lo dé por bueno.

Hasta ahora registrar una devolución era un solo acto: bodega escribía la
cifra y en ese mismo instante se descontaba el saldo del taller y se movía el
estado del lote. Eso obliga a que la cifra sea correcta a la primera, y por
eso el sistema la rechazaba con un 422 cuando no cuadraba -- un 422 que,
además, le decía a bodega la cantidad exacta que se esperaba, o sea que le
regalaba justo el dato que el conteo a ciegas existe para ocultarle.

La operación real es de dos manos: bodega cuenta sin saber cuánto se envió y
anota lo que le dio; corte compara contra lo que mandó; si no coincide,
hablan; y solo cuando están de acuerdo se confirma. `conteos_recepcion`
guarda ese primer paso.

Es tabla nueva y no un estado dentro de `devoluciones` porque media docena de
consultas ya suman esa tabla para calcular el saldo de un taller. Un reporte
sin confirmar viviendo ahí obligaría a que todas se acordaran de filtrarlo, y
la que se olvidara daría por entregado algo que nadie revisó.

Las dos columnas de personas (contado_por_id / confirmado_por_id) son el
control de cuatro ojos escrito en la base: sin ellas, "lo revisaron dos
personas" es una costumbre y no un hecho que se pueda comprobar después.

Revision ID: d61397da4147
Revises: d5f2b8a71c39
"""
import sqlalchemy as sa
from alembic import op


revision = "d61397da4147"
down_revision = "d5f2b8a71c39"
branch_labels = None
depends_on = None


ESTADOS = ("reportado", "confirmado")
TIPO_ESTADO = "estado_conteo_enum"


def upgrade() -> None:
    op.create_table(
        "conteos_recepcion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("asignacion_id", sa.Integer(), nullable=False),
        sa.Column("cantidad_buena", sa.Integer(), nullable=False),
        sa.Column("cantidad_danada", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("estado", sa.Enum(*ESTADOS, name=TIPO_ESTADO), nullable=False),
        sa.Column("contado_por_id", sa.Integer(), nullable=True),
        sa.Column("confirmado_por_id", sa.Integer(), nullable=True),
        sa.Column("confirmado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("devolucion_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["asignacion_id"], ["asignaciones_taller.id"], ondelete="CASCADE"),
        # SET NULL y no CASCADE: borrar a una persona no puede borrarle el
        # historial a la empresa. La fila sobrevive sin nombre.
        sa.ForeignKeyConstraint(["confirmado_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contado_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["devolucion_id"], ["devoluciones.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conteos_recepcion_asignacion_id"), "conteos_recepcion", ["asignacion_id"]
    )
    op.create_index(op.f("ix_conteos_recepcion_empresa_id"), "conteos_recepcion", ["empresa_id"])
    # Indexado porque la consulta que más corre es "qué hay sin confirmar":
    # la abre corte cada vez que entra.
    op.create_index(op.f("ix_conteos_recepcion_estado"), "conteos_recepcion", ["estado"])
    op.create_index(op.f("ix_conteos_recepcion_fecha"), "conteos_recepcion", ["fecha"])


def downgrade() -> None:
    op.drop_index(op.f("ix_conteos_recepcion_fecha"), table_name="conteos_recepcion")
    op.drop_index(op.f("ix_conteos_recepcion_estado"), table_name="conteos_recepcion")
    op.drop_index(op.f("ix_conteos_recepcion_empresa_id"), table_name="conteos_recepcion")
    op.drop_index(op.f("ix_conteos_recepcion_asignacion_id"), table_name="conteos_recepcion")
    op.drop_table("conteos_recepcion")

    # `drop_table` NO borra el tipo: en Postgres un ENUM es un objeto del
    # esquema, independiente de la tabla que lo usaba. Sin esta línea, revertir
    # y volver a aplicar falla con "type estado_conteo_enum already exists", y
    # falla en el despliegue -- en SQLite el tipo no existe, así que los tests
    # no lo verían nunca.
    if op.get_bind().dialect.name == "postgresql":
        sa.Enum(*ESTADOS, name=TIPO_ESTADO).drop(op.get_bind(), checkfirst=True)
