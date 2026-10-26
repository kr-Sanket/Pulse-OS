"""create audit_batch_anchors table (ADR-035)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-26

ADR-035: one row per (sealed batch, public network) recording the submission of the batch's
opaque commitment to the on-chain registry — network, chain id, contract, transaction hash,
block, status. Additive only: ``audit_logs``, ``audit_batches`` and ``audit_batch_members``
are unaltered; downgrade drops only this table — and with it every local submission record
(on-chain commitments are unaffected and are re-adopted by ``anchor`` after re-upgrading).
See docs/DATABASE_DESIGN.md §Downgrade and recovery.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_batch_anchors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("chain_id", sa.BigInteger(), nullable=False),
        sa.Column("contract_address", sa.String(length=42), nullable=False),
        sa.Column("commitment", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_batch_anchors")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["audit_batches.id"],
            name=op.f("fk_audit_batch_anchors_audit_batches_batch_id"),
        ),
        sa.UniqueConstraint(
            "batch_id", "network", name=op.f("uq_audit_batch_anchors_batch_id_network")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'FAILED')",
            name=op.f("ck_audit_batch_anchors_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'CONFIRMED' OR (tx_hash IS NOT NULL AND block_number IS NOT NULL)",
            name=op.f("ck_audit_batch_anchors_confirmed_has_evidence"),
        ),
        sa.CheckConstraint(
            "status <> 'PENDING' OR tx_hash IS NOT NULL",
            name=op.f("ck_audit_batch_anchors_pending_has_tx"),
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_batch_anchors")
