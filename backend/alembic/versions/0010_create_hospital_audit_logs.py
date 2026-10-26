"""create hospital_audit_logs table (ADR-034)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-26

ADR-034 (Slice 2): Append-only audit trail for administrative hospital verification
lifecycle transitions (VERIFIED, REJECTED, SUSPENDED, REINSTATED).

Downgrade drops the table and with it the whole lifecycle history (unrecoverable). It does not
touch ``hospitals.verification_status``: rows left REJECTED or SUSPENDED will not map in
pre-ADR-034 code. See docs/DATABASE_DESIGN.md §Downgrade and recovery.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hospital_audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospital_audit_logs")),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_hospital_audit_logs_hospitals_hospital_id"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_hospital_audit_logs_users_actor_user_id"),
        ),
        sa.CheckConstraint(
            "action IN ('VERIFIED', 'REJECTED', 'SUSPENDED', 'REINSTATED')",
            name=op.f("ck_hospital_audit_logs_action_valid"),
        ),
    )
    op.create_index(
        op.f("ix_hospital_audit_logs_hospital_id_occurred_at_id"),
        "hospital_audit_logs",
        ["hospital_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_hospital_audit_logs_hospital_id_occurred_at_id"),
        table_name="hospital_audit_logs",
    )
    op.drop_table("hospital_audit_logs")
