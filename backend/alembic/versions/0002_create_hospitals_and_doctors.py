"""create hospitals and doctors tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Physical schema for hospitals' ``hospitals`` and doctors' ``doctors`` (docs/DOMAIN_MODEL.md
§1, reviewed against docs/DATABASE_DESIGN.md). Constraint and index names follow the
metadata naming convention in app/core/db.py.
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
        sa.Column("hospital_id", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospitals")),
        sa.UniqueConstraint("hospital_id", name=op.f("uq_hospitals_hospital_id")),
    )
    op.create_table(
        "doctors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("registration_number", sa.String(length=50), nullable=False),
        sa.Column("specialty", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_doctors_hospitals_hospital_id")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_doctors_users_user_id")),
        sa.UniqueConstraint("registration_number", name=op.f("uq_doctors_registration_number")),
        sa.UniqueConstraint("user_id", name=op.f("uq_doctors_user_id")),
    )
    op.create_index(op.f("ix_doctors_hospital_id"), "doctors", ["hospital_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_doctors_hospital_id"), table_name="doctors")
    op.drop_table("doctors")
    op.drop_table("hospitals")
