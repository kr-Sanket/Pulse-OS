"""create hospitals and record_categories tables (M0.3 seed scope)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Reference tables for the seed system (scripts/seed.py): the three simulated hospitals
and the record-category controlled vocabulary (docs/DOMAIN_MODEL.md §1 — a seedable
table, not a code enum). Enum-valued columns are plain VARCHAR as in revision 0001.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hospitals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hid", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospitals")),
        sa.UniqueConstraint("hid", name=op.f("uq_hospitals_hid")),
    )
    op.create_table(
        "record_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_categories")),
        sa.UniqueConstraint("code", name=op.f("uq_record_categories_code")),
    )


def downgrade() -> None:
    # Every migration must be reversible (docs/DATABASE_DESIGN.md §Principles).
    op.drop_table("record_categories")
    op.drop_table("hospitals")
