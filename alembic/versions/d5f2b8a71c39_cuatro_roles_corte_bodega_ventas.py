"""cuatro roles: admin, corte, bodega, ventas

El sistema nació con dos roles (admin / operador) porque solo había dos
formas de usarlo: el dueño y "el que captura". La operación real tiene
cuatro puestos distintos, uno por persona: CORTE registra y asigna a los
talleres, BODEGA recibe y clasifica lo que vuelve, VENTAS despacha lo que
está listo, y ADMIN además crea los usuarios.

`operador` desaparece. En Postgres el tipo es un ENUM NATIVO
(ver el baseline a13f7a3aca7a, `sa.Enum('admin','operador',
name='rol_usuario_enum')`) y Postgres no tiene `ALTER TYPE ... DROP VALUE`:
para quitar un valor hay que crear un tipo nuevo, castear la columna y
borrar el viejo. Eso es lo que hace la rama de Postgres de aquí abajo.

En SQLite (los tests y el CI) el mismo Enum es un VARCHAR sin CHECK
-- `create_constraint` es False por defecto desde SQLAlchemy 1.4 -- y lo
único que cambia es la longitud declarada, 8 ('operador') -> 6 ('bodega').
Parece cosmético y no lo es: alembic/env.py configura compare_type=True, así
que `alembic check` compara VARCHAR(8) contra VARCHAR(6) y falla si esta
migración no toca la columna. Verificado con alembic.autogenerate:
    ('modify_type', ..., 'usuarios', 'rol', VARCHAR(length=8),
     Enum('admin','corte','bodega','ventas', name='rol_usuario_enum'))

Qué pasa con los `operador` que ya existan: se convierten en `corte`. En
producción hoy no hay ninguno (el único usuario es el ADMIN), así que en
la práctica esta migración no mueve ni una fila de datos; el mapeo está
para que la migración sea correcta en cualquier base. Se escribe un aviso
en el log con los correos afectados porque "una sola persona por rol" y
varios operadores convertidos a CORTE de golpe es algo que un humano tiene
que revisar a mano.

Revision ID: d5f2b8a71c39
Revises: c4a83f1e6db0
"""
import logging

from alembic import context, op
import sqlalchemy as sa


revision = "d5f2b8a71c39"
down_revision = "c4a83f1e6db0"
branch_labels = None
depends_on = None


ROLES_NUEVOS = ("admin", "corte", "bodega", "ventas")
ROLES_VIEJOS = ("admin", "operador")

TIPO = "rol_usuario_enum"
TIPO_TEMPORAL = "rol_usuario_enum_tmp"

# Longitudes que SQLAlchemy le da al VARCHAR en SQLite: el valor más largo
# de cada juego de roles ('operador' = 8, 'bodega'/'ventas' = 6).
LARGO_VIEJO = 8
LARGO_NUEVO = 6

log = logging.getLogger("alembic.runtime.migration")


def _avisar_de_los_operadores(bind, destino: str) -> None:
    """Deja constancia en el log de a quién se le está cambiando el rol.

    `rol = 'operador'` funciona igual en Postgres (el literal se castea al
    enum) y en SQLite (es texto), así que no hace falta partir la consulta.

    En modo offline (`alembic upgrade --sql`, que solo imprime el SQL) no hay
    conexión contra la cual consultar: `op.get_bind()` devuelve algo que no
    ejecuta nada. Sin esta guarda, generar el script SQL revienta.
    """
    if context.is_offline_mode():
        return
    filas = bind.execute(
        sa.text("SELECT id, email FROM usuarios WHERE rol = 'operador'")
    ).fetchall()
    if not filas:
        return
    log.warning(
        "%d usuario(s) con rol 'operador' pasan a '%s'. Revisar a mano, el "
        "modelo es de una sola persona por rol: %s",
        len(filas),
        destino,
        ", ".join(f"#{fila.id} {fila.email}" for fila in filas),
    )


def _revisar_que_nadie_mas_use_el_tipo(bind) -> None:
    """`DROP TYPE` falla si algo más depende del tipo.

    La base de producción se creó a mano en Supabase antes de que existiera
    Alembic (ver el baseline), así que puede haber vistas o políticas que el
    esquema de los modelos no conoce. Mejor reventar acá con una lista de
    culpables que con el error genérico de Postgres a mitad del deploy.
    """
    if context.is_offline_mode():
        return
    usos = bind.execute(
        sa.text(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE udt_name = :tipo
              AND NOT (table_name = 'usuarios' AND column_name = 'rol')
            """
        ),
        {"tipo": TIPO},
    ).fetchall()
    if usos:
        detalle = ", ".join(f"{u.table_schema}.{u.table_name}.{u.column_name}" for u in usos)
        raise RuntimeError(
            f"El tipo {TIPO} lo usa algo más aparte de usuarios.rol ({detalle}). "
            "Hay que migrar esas columnas en la misma migración; si no, el "
            "DROP TYPE va a fallar."
        )


def upgrade() -> None:
    bind = op.get_bind()
    _avisar_de_los_operadores(bind, "corte")

    if bind.dialect.name == "postgresql":
        _revisar_que_nadie_mas_use_el_tipo(bind)
        # La columna arrastra un DEFAULT ligado al tipo viejo que el baseline no
        # declara pero que SI existe en produccion. Verificado contra Supabase:
        #     column_default = "'operador'::rol_usuario_enum"
        # Postgres se niega a cambiar el tipo de una columna cuyo default depende
        # de el, asi que sin este DROP la migracion habria reventado en el
        # despliegue y no en los tests -- en SQLite no hay tipo que arrastrar.
        #
        # No se repone despues a proposito: con cuatro puestos, un INSERT que
        # olvida el rol no debe elegirlo por su cuenta. El modelo tampoco pone
        # default (app/models/usuario.py) y el schema lo exige.
        op.execute(sa.text("ALTER TABLE usuarios ALTER COLUMN rol DROP DEFAULT"))
        op.execute(
            sa.text(
                "CREATE TYPE %s AS ENUM ('admin','corte','bodega','ventas')"
                % TIPO_TEMPORAL
            )
        )
        # El CASE traduce durante el cast. No se puede hacer un UPDATE antes
        # (`SET rol = 'corte'`) porque 'corte' todavía no existe en el tipo
        # viejo, ni después (la columna ya no admitiría 'operador').
        op.execute(
            sa.text(
                """
                ALTER TABLE usuarios
                    ALTER COLUMN rol TYPE {tipo}
                    USING (
                        CASE rol::text
                            WHEN 'operador' THEN 'corte'
                            ELSE rol::text
                        END
                    )::{tipo}
                """.format(tipo=TIPO_TEMPORAL)
            )
        )
        # La columna ya no depende del tipo viejo, así que se puede borrar y
        # dejarle el nombre de siempre al nuevo. Sin el rename, el modelo
        # (name="rol_usuario_enum") y la base dejarían de coincidir.
        op.execute(sa.text("DROP TYPE %s" % TIPO))
        op.execute(sa.text("ALTER TYPE %s RENAME TO %s" % (TIPO_TEMPORAL, TIPO)))
        return

    # SQLite: primero los datos (es texto libre, no hay tipo que lo impida)
    # y después la longitud declarada, que es lo que mira `alembic check`.
    op.execute(sa.text("UPDATE usuarios SET rol = 'corte' WHERE rol = 'operador'"))
    with op.batch_alter_table("usuarios") as batch:
        batch.alter_column(
            "rol",
            existing_type=sa.VARCHAR(length=LARGO_VIEJO),
            type_=sa.Enum(*ROLES_NUEVOS, name=TIPO),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()

    # Vuelta atrás con pérdida y no hay otra: el tipo viejo solo tiene dos
    # valores, así que corte, bodega y ventas colapsan los tres en
    # 'operador'. Quién era quién no se puede reconstruir después.
    if not context.is_offline_mode():
        filas = bind.execute(
            sa.text(
                "SELECT id, email, rol FROM usuarios "
                "WHERE rol IN ('corte','bodega','ventas')"
            )
        ).fetchall()
        if filas:
            log.warning(
                "%d usuario(s) pierden su rol y quedan como 'operador': %s",
                len(filas),
                ", ".join(f"#{fila.id} {fila.email} ({fila.rol})" for fila in filas),
            )

    if bind.dialect.name == "postgresql":
        _revisar_que_nadie_mas_use_el_tipo(bind)
        # Defensivo: el upgrade ya dejo la columna sin DEFAULT, asi que aqui
        # normalmente no hay nada que quitar y el DROP es un no-op. Se ejecuta
        # igual porque revertir tiene que funcionar tambien sobre una base que
        # alguien haya tocado a mano, y con un default puesto el ALTER TYPE de
        # abajo fallaria.
        op.execute(sa.text("ALTER TABLE usuarios ALTER COLUMN rol DROP DEFAULT"))
        op.execute(
            sa.text("CREATE TYPE %s AS ENUM ('admin','operador')" % TIPO_TEMPORAL)
        )
        op.execute(
            sa.text(
                """
                ALTER TABLE usuarios
                    ALTER COLUMN rol TYPE {tipo}
                    USING (
                        CASE rol::text
                            WHEN 'admin' THEN 'admin'
                            ELSE 'operador'
                        END
                    )::{tipo}
                """.format(tipo=TIPO_TEMPORAL)
            )
        )
        op.execute(sa.text("DROP TYPE %s" % TIPO))
        op.execute(sa.text("ALTER TYPE %s RENAME TO %s" % (TIPO_TEMPORAL, TIPO)))
        # Se restituye el default que la base tenia antes del upgrade, para que
        # revertir deje la columna exactamente como estaba.
        op.execute(
            sa.text("ALTER TABLE usuarios ALTER COLUMN rol SET DEFAULT 'operador'")
        )
        return

    op.execute(
        sa.text(
            "UPDATE usuarios SET rol = 'operador' "
            "WHERE rol IN ('corte','bodega','ventas')"
        )
    )
    with op.batch_alter_table("usuarios") as batch:
        batch.alter_column(
            "rol",
            existing_type=sa.VARCHAR(length=LARGO_NUEVO),
            type_=sa.Enum(*ROLES_VIEJOS, name=TIPO),
            existing_nullable=False,
        )
