"""create notifications table (ADR-031)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-13

ADR-031 (M4). New table, **additive only**: stores in-app notifications for patients and
clinicians. Created within the same database transaction as triggering consent actions.

- ``recipient_user_id`` FK to ``users.id``: standard PulseOS convention (no CASCADE,
  users are tombstoned/suspended rather than physically deleted).
- Generic administrative title and message with zero PHI, zero diagnoses, zero clinical
  categories, and zero health identifiers.
- Minimal nullable structured reference foreign keys (``reference_request_id``,
  ``actor_doctor_id``, ``actor_hospital_id``) for client routing without duplicating display copy.
- Composite indexes for unread count filtering and keyset cursor pagination.

Downgrade drops the table and indexes cleanly.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("reference_request_id", sa.Uuid(), nullable=True),
        sa.Column("actor_doctor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_hospital_id", sa.Uuid(), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name=op.f("fk_notifications_users_recipient_user_id"),
        ),
        sa.ForeignKeyConstraint(
            ["reference_request_id"],
            ["consent_requests.id"],
            name=op.f("fk_notifications_consent_requests_reference_request_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_doctor_id"],
            ["doctors.id"],
            name=op.f("fk_notifications_doctors_actor_doctor_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_notifications_hospitals_actor_hospital_id"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_notifications_recipient_unread_created"),
        "notifications",
        ["recipient_user_id", "is_read", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_recipient_created"),
        "notifications",
        ["recipient_user_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_notifications_recipient_created"),
        table_name="notifications",
    )
    op.drop_index(
        op.f("ix_notifications_recipient_unread_created"),
        table_name="notifications",
    )
    op.drop_table("notifications")
