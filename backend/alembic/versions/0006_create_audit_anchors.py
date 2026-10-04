"""create audit_anchors — blockchain integrity anchors for audit events

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-08

ADR-026 (and ADR-004, which reserved this table from M3). One new table. **No existing row
is read, rewritten or backfilled**, and ``audit_logs`` is not touched at all — the trail
stays exactly as it was, and every event written before this revision simply has no anchor.
That is a first-class state (``NOT_ANCHORED``), not a defect to repair.

**No backfill, deliberately.** Anchoring the 200-odd existing events would be *technically*
safe — anchoring reads a digest and writes a separate row — but it would be dishonest: an
anchor asserts "this digest existed at this time", and stamping today's timestamp onto an
event from last week asserts something false about when it was witnessed. Legacy events are
therefore left unanchored, and the sweep anchors them only if an operator chooses to run it
(``scripts/anchor_audit_events.py``), which records today as the anchoring time truthfully.

**One anchor per event, enforced here.** ``audit_log_id`` is UNIQUE rather than merely
indexed: idempotency is then a database guarantee that survives concurrent sweeps, instead
of a check-then-insert that races. The service reads the winner back when it loses.

**The table holds no event content.** A digest, the scheme that produced it, a network name,
a transaction reference and a timestamp. No actor, no patient, no action, no target — those
remain in ``audit_logs``, which stays authoritative (docs/BLOCKCHAIN_ARCHITECTURE.md).

Downgrade drops the table. Reversible with no loss to the audit trail itself: anchors are
derived evidence and can be recreated by re-running the sweep, though the recreated
``anchored_at`` would be the new run's time — see the no-backfill note above.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_anchors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("audit_log_id", sa.Uuid(), nullable=False),
        # The event digest exactly as published — the same width as audit_logs.event_hash.
        sa.Column("digest", sa.String(length=64), nullable=False),
        # Which hashing scheme produced the digest (ADR-023 v1/v2; v3 is ADR-019's keccak).
        # Stored so an anchor can never be compared across algorithms by accident.
        sa.Column("hash_version", sa.SmallInteger(), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(length=80), nullable=False),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_anchors")),
        sa.ForeignKeyConstraint(
            ["audit_log_id"],
            ["audit_logs.id"],
            name=op.f("fk_audit_anchors_audit_logs_audit_log_id"),
        ),
        # The idempotency guarantee, not an optimisation.
        sa.UniqueConstraint("audit_log_id", name=op.f("uq_audit_anchors_audit_log_id")),
    )
    op.create_index(op.f("ix_audit_anchors_anchored_at"), "audit_anchors", ["anchored_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_anchors_anchored_at"), table_name="audit_anchors")
    op.drop_table("audit_anchors")
