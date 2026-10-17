"""add hospital verification metadata (ADM-01)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17

ADM-01: Accountability for hospital verification. Adds nullable verifier identity
and verification timestamp to the care organizations table (``hospitals``).

- ``verified_by_user_id``: UUID, nullable, foreign key to ``users.id``.
  Referential integrity only, following the PulseOS cross-module convention.
  Users are suspended/tombstoned rather than physically deleted (no CASCADE).
- ``verified_at``: timezone-aware timestamp, nullable.

Both columns are nullable so existing pre-verified and self-registered PENDING
hospitals remain valid without data backfill.

Downgrade drops the foreign key constraint and both columns cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _hospitals_table(*, with_0009: bool) -> sa.Table:
    """``hospitals`` as a literal snapshot — before this migration, or after it.

    Batch mode normally reflects the table from a live connection, which offline (``--sql``)
    mode has none of. Handing it an explicit definition lets one migration file serve online
    Postgres, online SQLite and offline generation alike.
    """
    columns: list[sa.schema.SchemaItem] = [
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
        sa.PrimaryKeyConstraint("id", name="pk_hospitals"),
        sa.UniqueConstraint("hid", name="uq_hospitals_hid"),
    ]
    if with_0009:
        columns.extend(
            [
                sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
                sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
                sa.ForeignKeyConstraint(
                    ["verified_by_user_id"],
                    ["users.id"],
                    name="fk_hospitals_users_verified_by_user_id",
                ),
            ]
        )
    return sa.Table("hospitals", sa.MetaData(), *columns)


def upgrade() -> None:
    with op.batch_alter_table("hospitals", copy_from=_hospitals_table(with_0009=False)) as batch:
        batch.add_column(sa.Column("verified_by_user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_hospitals_users_verified_by_user_id",
            "users",
            ["verified_by_user_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("hospitals", copy_from=_hospitals_table(with_0009=True)) as batch:
        batch.drop_constraint("fk_hospitals_users_verified_by_user_id", type_="foreignkey")
        batch.drop_column("verified_at")
        batch.drop_column("verified_by_user_id")
