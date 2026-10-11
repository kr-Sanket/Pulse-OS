"""create audit_batches and audit_batch_members — Merkle-batched v3 anchoring

Revision ID: 0007
Revises: aedb0169a4eb
Create Date: 2026-10-11

ADR-027 (M6.3). Two new tables, **additive only**: ``audit_logs`` and ``audit_anchors`` are not
touched, no existing row is read, rewritten or backfilled. v1/v2 events are never batched; v3
events written before this revision are sealed by the first sealing run, which records its
own time truthfully — the same honesty rule migration 0006 states.

**Both tables are evidence written once** — no ``updated_at``, no status column. Integrity
verdicts are computed on demand by reconciliation (ADR-027 decision 9).

**The constraints are the concurrency design, not decoration:**

* ``audit_batches.batch_number`` UNIQUE — two sealers cannot both claim the next number;
* ``audit_batch_members.audit_log_id`` UNIQUE — one batch per event, ever;
* ``(batch_id, leaf_index)`` UNIQUE — one event per position;
* CHECKs: ``batch_number >= 1``, ``leaf_count >= 1`` (no empty batch can exist even if the
  service were bypassed), ``hash_version = 3`` and ``leaf_index >= 0``.

``commitment`` is UNIQUE too: it binds ``batch_number``, so a collision means a duplicated
batch, and it is the key a chain-side lookup will use. No event content is stored: members
carry an event id, a position and the sealed digest.

Downgrade drops both tables (members first). The audit trail is unaffected; sealed batches
are derived evidence, though re-sealing would assign new numbers and record a new time.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "aedb0169a4eb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_number", sa.BigInteger(), nullable=False),
        sa.Column("protocol_version", sa.SmallInteger(), nullable=False),
        sa.Column("hash_version", sa.SmallInteger(), nullable=False),
        sa.Column("leaf_count", sa.Integer(), nullable=False),
        sa.Column("root", sa.String(length=64), nullable=False),
        sa.Column("commitment", sa.String(length=64), nullable=False),
        sa.Column("first_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_batches")),
        sa.UniqueConstraint("batch_number", name=op.f("uq_audit_batches_batch_number")),
        sa.UniqueConstraint("commitment", name=op.f("uq_audit_batches_commitment")),
        sa.CheckConstraint(
            "batch_number >= 1", name=op.f("ck_audit_batches_batch_number_positive")
        ),
        sa.CheckConstraint("leaf_count >= 1", name=op.f("ck_audit_batches_leaf_count_positive")),
        sa.CheckConstraint("hash_version = 3", name=op.f("ck_audit_batches_hash_version_v3")),
    )
    op.create_table(
        "audit_batch_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("audit_log_id", sa.Uuid(), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_batch_members")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["audit_batches.id"],
            name=op.f("fk_audit_batch_members_audit_batches_batch_id"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_log_id"],
            ["audit_logs.id"],
            name=op.f("fk_audit_batch_members_audit_logs_audit_log_id"),
        ),
        sa.UniqueConstraint("audit_log_id", name=op.f("uq_audit_batch_members_audit_log_id")),
        sa.UniqueConstraint(
            "batch_id", "leaf_index", name=op.f("uq_audit_batch_members_batch_id_leaf_index")
        ),
        sa.CheckConstraint(
            "leaf_index >= 0", name=op.f("ck_audit_batch_members_leaf_index_non_negative")
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_batch_members")
    op.drop_table("audit_batches")
