"""create users and patients tables (M0.3 part 3a)

Revision ID: 0001
Revises:
Create Date: 2026-08-28

First physical schema: auth's ``users`` and patients' ``patients`` (docs/DOMAIN_MODEL.md
§1, reviewed against docs/DATABASE_DESIGN.md). Enum-valued columns are plain VARCHAR
(non-native, no CHECK) — values are enforced by the typed application layer, and adding a
role/gender must not require a constraint migration. Constraint names follow the metadata
naming convention in app/core/db.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("firebase_uid", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("firebase_uid", name=op.f("uq_users_firebase_uid")),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("health_id", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=10), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patients")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_patients_users_user_id")),
        sa.UniqueConstraint("user_id", name=op.f("uq_patients_user_id")),
        sa.UniqueConstraint("health_id", name=op.f("uq_patients_health_id")),
    )


def downgrade() -> None:
    # Every migration must be reversible (docs/DATABASE_DESIGN.md §Principles).
    op.drop_table("patients")
    op.drop_table("users")
