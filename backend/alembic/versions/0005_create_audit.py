"""create audit_events table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28

Physical schema for audit's ``audit_events`` (docs/DOMAIN_MODEL.md §1,
reviewed against docs/DATABASE_DESIGN.md and ADR-004). Constraint and index
names follow the metadata naming convention in app/core/db.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(length=30), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_context", sa.JSON(), nullable=True),
        sa.Column("canonical_hash", sa.String(length=64), nullable=False),
        sa.Column("anchor_status", sa.String(length=20), nullable=False),
        sa.Column("anchor_tx_hash", sa.String(length=100), nullable=True),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_events_users_actor_id")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_audit_events_patients_patient_id")
        ),
    )
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"], unique=False)
    op.create_index(
        op.f("ix_audit_events_canonical_hash"), "audit_events", ["canonical_hash"], unique=False
    )
    op.create_index(
        op.f("ix_audit_events_patient_id"), "audit_events", ["patient_id"], unique=False
    )
    op.create_index(op.f("ix_audit_events_target_id"), "audit_events", ["target_id"], unique=False)
    op.create_index(op.f("ix_audit_events_timestamp"), "audit_events", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_timestamp"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_target_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_patient_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_canonical_hash"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_table("audit_events")
