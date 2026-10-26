"""removed listings (cleanup: too old / ineligible)

Revision ID: b7c1d2e3f4a5
Revises: e4fd136de86c
Create Date: 2026-10-18 20:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c1d2e3f4a5'
down_revision = 'e4fd136de86c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('removed_listings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('canonical_key', sa.String(length=400), nullable=False),
    sa.Column('company', sa.String(length=300), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=True),
    sa.Column('reason', sa.String(length=40), nullable=False),
    sa.Column('removed_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canonical_key')
    )
    with op.batch_alter_table('removed_listings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_removed_listings_removed_at'), ['removed_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('removed_listings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_removed_listings_removed_at'))
    op.drop_table('removed_listings')
