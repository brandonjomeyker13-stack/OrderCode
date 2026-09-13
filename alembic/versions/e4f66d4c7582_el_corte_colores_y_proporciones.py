"""el corte: colores y proporciones

Un corte es un TENDIDO de tela: se apilan capas y se corta todo junto. De un
mismo corte salen varios tipos de producto en varios colores, y esa
combinación -- corte + tipo + color -- es la unidad de la que se habla en
planta. Hasta ahora el sistema solo sabía de "un tipo de producto y una
cantidad", que es media verdad.

LO QUE NO SE HACE, Y ES LA DECISIÓN QUE ABARATA TODO
No se renombra `lotes` ni se mueve un solo id. De `lotes.id` cuelgan
asignaciones, devoluciones, incidencias, conteos de recepción, ventas y las
Idempotency-Keys ya emitidas: son 111 referencias. Esta migración solo AGREGA
columnas y tablas; ni una fila cambia de identidad, y por eso el downgrade es
el inverso exacto.

`lotes` pasa a significar "una línea del corte". El nombre queda debiendo, y
se puede renombrar después en un commit mecánico -- pero renombrar no compra
seguridad, y hacerlo a la vez que el modelo sí cuesta riesgo.

EL CORTE NO TIENE ESTADO
A propósito. El avance ("6 líneas: 4 cerradas, 2 en taller") se calcula
sumando las líneas cuando alguien pregunta. Un estado guardado aquí sería un
segundo sitio donde vive la misma verdad, y dos sitios se desincronizan: basta
con que un admin corrija una devolución vieja para que el estado del corte
quede mintiendo. Y de paso: sin estado no hay tipo ENUM nuevo en Postgres, que
es lejos lo más caro de migrar en esta base (ver d5f2b8a71c39).

LOS DOS ARREGLOS SOBRE LO QUE GENERÓ ALEMBIC
1. Las columnas nuevas de `empresas` salían NOT NULL sin server_default.
   Postgres rechaza eso sobre una tabla con filas, y SQLite también -- pero en
   los tests la tabla está vacía cuando corre la migración, así que habría
   pasado en verde y reventado en el despliegue. Van con server_default.
2. `op.drop_constraint(None, ...)` en el downgrade: un nombre None no es
   nombre. Las dos llaves foráneas se crean con nombre explícito.

QUÉ PASA CON LOS LOTES QUE YA EXISTEN
Se les crea un corte propio a cada uno, con `origen_lote_id` apuntando de
vuelta -- así el "#32" que el cliente ve hoy en pantalla no se pierde. Su
`numero` queda en NULL: son históricos y nunca estuvieron en el ciclo 01-100,
y NULL dice eso mejor que un número inventado. El UNIQUE no se queja porque
en Postgres y en SQLite dos NULL no chocan entre sí.

El color de esos lotes queda NULL y así se queda: no está guardado en ningún
lado y no se puede adivinar.

Revision ID: e4f66d4c7582
Revises: 5690baa95acb
"""
import sqlalchemy as sa
from alembic import op


revision = "e4f66d4c7582"
down_revision = "5690baa95acb"
branch_labels = None
depends_on = None


FK_CORTE = "fk_lotes_corte_id_cortes"
FK_COLOR = "fk_lotes_color_id_colores"


def upgrade() -> None:
    op.create_table(
        "colores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=60), nullable=False),
        sa.Column("nombre_normalizado", sa.String(length=60), nullable=False),
        sa.Column("hex", sa.String(length=7), nullable=True),
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
        # Sobre el nombre NORMALIZADO, no sobre el que se escribe: así "Azul
        # Rey" y "azul rey" chocan, que es justo lo que se quiere.
        sa.UniqueConstraint("empresa_id", "nombre_normalizado", name="uq_color_nombre_empresa"),
    )
    op.create_index(op.f("ix_colores_empresa_id"), "colores", ["empresa_id"])

    op.create_table(
        "cortes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("empresa_id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.SmallInteger(), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("cantidad_declarada", sa.Integer(), nullable=True),
        sa.Column("cerrado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origen_lote_id", sa.Integer(), nullable=True),
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
        sa.UniqueConstraint("empresa_id", "numero", "fecha", name="uq_corte_numero_fecha_empresa"),
    )
    op.create_index(op.f("ix_cortes_empresa_id"), "cortes", ["empresa_id"])
    op.create_index(op.f("ix_cortes_fecha"), "cortes", ["fecha"])

    # server_default obligatorio: son NOT NULL y `empresas` tiene filas.
    op.add_column(
        "empresas",
        sa.Column("corte_numero_max", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "empresas",
        sa.Column("corte_ultimo_numero", sa.Integer(), nullable=False, server_default="0"),
    )

    # batch_alter_table y no add_column suelto: SQLite no sabe hacer ALTER de
    # constraints ("No support for ALTER of constraints in SQLite dialect"),
    # y saltarse las llaves foráneas allí tampoco vale -- `alembic check`
    # compara llaves foráneas y el CI se pone rojo. En Postgres batch emite
    # ALTER normales; solo en SQLite recrea la tabla, y ahí no hay datos que
    # perder porque es la base de los tests.
    with op.batch_alter_table("lotes") as lotes:
        lotes.add_column(sa.Column("corte_id", sa.Integer(), nullable=True))
        lotes.add_column(sa.Column("color_id", sa.Integer(), nullable=True))
        lotes.add_column(sa.Column("proporciones", sa.Integer(), nullable=True))
        lotes.create_foreign_key(FK_CORTE, "cortes", ["corte_id"], ["id"], ondelete="RESTRICT")
        lotes.create_foreign_key(FK_COLOR, "colores", ["color_id"], ["id"], ondelete="RESTRICT")

    op.create_index(op.f("ix_lotes_color_id"), "lotes", ["color_id"])
    op.create_index(op.f("ix_lotes_corte_id"), "lotes", ["corte_id"])

    # --- Un corte por cada lote que ya existía ---
    #
    # Se hace en SQL y no con el ORM a propósito: una migración que importa
    # los modelos se rompe el día que el modelo cambie, y este archivo tiene
    # que seguir aplicando igual dentro de un año.
    op.execute(
        sa.text(
            """
            INSERT INTO cortes (empresa_id, numero, fecha, origen_lote_id)
            SELECT empresa_id, NULL, fecha_registro, id FROM lotes
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE lotes
            SET corte_id = (SELECT c.id FROM cortes c WHERE c.origen_lote_id = lotes.id)
            """
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lotes_corte_id"), table_name="lotes")
    op.drop_index(op.f("ix_lotes_color_id"), table_name="lotes")
    with op.batch_alter_table("lotes") as lotes:
        lotes.drop_constraint(FK_COLOR, type_="foreignkey")
        lotes.drop_constraint(FK_CORTE, type_="foreignkey")
        lotes.drop_column("proporciones")
        lotes.drop_column("color_id")
        lotes.drop_column("corte_id")
    op.drop_column("empresas", "corte_ultimo_numero")
    op.drop_column("empresas", "corte_numero_max")
    op.drop_index(op.f("ix_cortes_fecha"), table_name="cortes")
    op.drop_index(op.f("ix_cortes_empresa_id"), table_name="cortes")
    op.drop_table("cortes")
    op.drop_index(op.f("ix_colores_empresa_id"), table_name="colores")
    op.drop_table("colores")
