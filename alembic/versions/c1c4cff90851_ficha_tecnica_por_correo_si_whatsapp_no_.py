"""ficha tecnica por correo si whatsapp no esta disponible

Escrita a mano sobre lo que generó autogenerate: Alembic no reconoce los
renombres y proponía borrar `notificaciones_whatsapp` y crear `notificaciones`
desde cero, lo que se llevaría por delante todo el historial de envíos. Acá se
hace como lo que realmente es -- un renombre de tabla más una columna nueva --
para que los registros existentes se conserven.

Revision ID: c1c4cff90851
Revises: ec971ea348c7
Create Date: 2026-08-06 17:56:16.064790

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c1c4cff90851'
down_revision: Union[str, None] = 'ec971ea348c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El tipo enum se declara una sola vez para poder crearlo y borrarlo
# explícitamente: en Postgres un ENUM es un objeto propio de la base, no
# solo una restricción de la columna.
canal_enum = sa.Enum('whatsapp', 'correo', name='canal_notificacion_enum')


def upgrade() -> None:
    op.add_column('talleres', sa.Column('email', sa.String(length=255), nullable=True))

    op.drop_index('ix_notificaciones_whatsapp_asignacion_id', table_name='notificaciones_whatsapp')
    op.drop_index('ix_notificaciones_whatsapp_empresa_id', table_name='notificaciones_whatsapp')
    op.rename_table('notificaciones_whatsapp', 'notificaciones')

    canal_enum.create(op.get_bind(), checkfirst=True)
    # Se agrega admitiendo nulos para poder rellenar las filas que ya existen;
    # recién después se exige el valor. Al revés fallaría en cualquier base con
    # datos. batch_alter_table es lo que hace que el ALTER también funcione en
    # SQLite, que no lo soporta de forma nativa.
    with op.batch_alter_table('notificaciones') as batch:
        batch.add_column(sa.Column('canal', canal_enum, nullable=True))

    # Todo lo registrado antes de este cambio salió por WhatsApp: era el único
    # canal que existía.
    op.execute("UPDATE notificaciones SET canal = 'whatsapp' WHERE canal IS NULL")

    with op.batch_alter_table('notificaciones') as batch:
        batch.alter_column('canal', existing_type=canal_enum, nullable=False)

    op.create_index(
        op.f('ix_notificaciones_asignacion_id'), 'notificaciones', ['asignacion_id'], unique=False
    )
    op.create_index(
        op.f('ix_notificaciones_empresa_id'), 'notificaciones', ['empresa_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_notificaciones_empresa_id'), table_name='notificaciones')
    op.drop_index(op.f('ix_notificaciones_asignacion_id'), table_name='notificaciones')

    with op.batch_alter_table('notificaciones') as batch:
        batch.drop_column('canal')
    canal_enum.drop(op.get_bind(), checkfirst=True)

    op.rename_table('notificaciones', 'notificaciones_whatsapp')
    op.create_index(
        'ix_notificaciones_whatsapp_empresa_id', 'notificaciones_whatsapp', ['empresa_id'], unique=False
    )
    op.create_index(
        'ix_notificaciones_whatsapp_asignacion_id', 'notificaciones_whatsapp', ['asignacion_id'], unique=False
    )

    op.drop_column('talleres', 'email')
