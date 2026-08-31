"""create the consent domain tables (M3: requests, requested categories, decisions,
grants, audit log)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-31

M3 physical schema (docs/DOMAIN_MODEL.md §1, ADR-004, ADR-013): the access-request
lifecycle and its requested categories, the immutable per-category decisions, the active
grants that enforcement reads, and the append-only audit log. Enum-valued columns are plain
VARCHAR (non-native, no CHECK) as in revisions 0001-0003 — values are enforced by the typed
application layer, so extending the audit vocabulary never requires a constraint migration.

Departures from 0003, each deliberate:

- **Composite indexes instead of single-column ones.** Every listing these tables serve is
  ``WHERE <scope> = ? ORDER BY <time> DESC, id DESC LIMIT n``; ``(scope, time, id)`` serves
  the predicate and the order together, so a page is an index range scan with no sort.
  Ascending column order is deliberate — Postgres reads the same index backwards for the
  descending walk, and it keeps the DDL dialect-neutral.
- **Two multi-column constraints are named explicitly** rather than relying on the
  convention's ``column_0_name`` template, which is ambiguous for multi-column constructs.
- **``consent_decisions`` takes a composite foreign key** into
  ``consent_request_categories`` instead of two independent references, so the database
  rejects a decision on a category the request never asked for. Per-column integrity still
  holds transitively through that table's own foreign keys.
- **Append-only tables carry ``created_at`` only** — no ``updated_at`` column and no
  ``onupdate`` hook, so the DDL cannot advertise a mutation that
  docs/DATABASE_DESIGN.md principle 3 forbids. ``consent_requests`` (status transitions)
  and ``consent_grants`` (revocation) are mutable and keep both timestamps.
- **``audit_logs.request_context`` is unbounded TEXT**, not a sized column: the
  ``X-Request-Id`` header it records is client-supplied and unvalidated, and a length
  ceiling would let an oversized header fail the INSERT and roll back the audited action
  with it.
- **``audit_logs.occurred_at``** is the application-assigned event time that
  ``event_hash`` covers; ``created_at`` is the server-assigned storage time and is not
  hashed. See app/modules/consent/models.py for why the hash cannot include a
  server-generated timestamp.

``AnchorReceipt`` (docs/DOMAIN_MODEL.md §2, ADR-004) is not created here: it must be a
separate table because ``audit_logs`` is append-only, and it lands with M6.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consent_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("requester_doctor_id", sa.Uuid(), nullable=False),
        sa.Column("requester_hospital_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_requests")),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_consent_requests_patients_patient_id")
        ),
        sa.ForeignKeyConstraint(
            ["requester_doctor_id"],
            ["doctors.id"],
            name=op.f("fk_consent_requests_doctors_requester_doctor_id"),
        ),
        sa.ForeignKeyConstraint(
            ["requester_hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_consent_requests_hospitals_requester_hospital_id"),
        ),
    )
    op.create_index(
        op.f("ix_consent_requests_patient_id_created_at_id"),
        "consent_requests",
        ["patient_id", "created_at", "id"],
    )
    op.create_index(
        op.f("ix_consent_requests_requester_doctor_id_created_at_id"),
        "consent_requests",
        ["requester_doctor_id", "created_at", "id"],
    )

    op.create_table(
        "consent_request_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_request_categories")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["consent_requests.id"],
            name=op.f("fk_consent_request_categories_consent_requests_request_id"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_consent_request_categories_record_categories_category_id"),
        ),
        # The requested set, and the parent key consent_decisions references so that a
        # decision can only answer a category the request actually asked for.
        sa.UniqueConstraint(
            "request_id",
            "category_id",
            name=op.f("uq_consent_request_categories_request_id_category_id"),
        ),
    )

    op.create_table(
        "consent_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_decisions")),
        # One decision per (request, category) — the cardinal rule of docs/DOMAIN_MODEL.md
        # §1, enforced by the database. This index also backs the composite FK below.
        sa.UniqueConstraint(
            "request_id", "category_id", name=op.f("uq_consent_decisions_request_id_category_id")
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "category_id"],
            ["consent_request_categories.request_id", "consent_request_categories.category_id"],
            name=op.f("fk_consent_decisions_consent_request_categories_request_id"),
        ),
    )

    op.create_table(
        "consent_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_doctor_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_grants")),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["consent_decisions.id"],
            name=op.f("fk_consent_grants_consent_decisions_decision_id"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_consent_grants_patients_patient_id")
        ),
        sa.ForeignKeyConstraint(
            ["grantee_doctor_id"],
            ["doctors.id"],
            name=op.f("fk_consent_grants_doctors_grantee_doctor_id"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_consent_grants_record_categories_category_id"),
        ),
        # One grant per approval: the guard against double-spawning on a retry.
        sa.UniqueConstraint("decision_id", name=op.f("uq_consent_grants_decision_id")),
    )
    # The ADR-013 layer-3 enforcement lookup, on the hot path of every non-owner read.
    op.create_index(
        op.f("ix_consent_grants_patient_id_grantee_doctor_id_category_id"),
        "consent_grants",
        ["patient_id", "grantee_doctor_id", "category_id"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("target_record_id", sa.Uuid(), nullable=True),
        sa.Column("target_category_id", sa.Uuid(), nullable=True),
        sa.Column("target_request_id", sa.Uuid(), nullable=True),
        # Unbounded on purpose: a client-supplied header must not be able to fail the
        # audit INSERT and roll back the action it records.
        sa.Column("request_context", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_logs_users_actor_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_audit_logs_patients_patient_id")
        ),
        sa.ForeignKeyConstraint(
            ["target_record_id"],
            ["medical_records.id"],
            name=op.f("fk_audit_logs_medical_records_target_record_id"),
        ),
        sa.ForeignKeyConstraint(
            ["target_category_id"],
            ["record_categories.id"],
            name=op.f("fk_audit_logs_record_categories_target_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["target_request_id"],
            ["consent_requests.id"],
            name=op.f("fk_audit_logs_consent_requests_target_request_id"),
        ),
    )
    op.create_index(
        op.f("ix_audit_logs_patient_id_occurred_at_id"),
        "audit_logs",
        ["patient_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    # Every migration must be reversible (docs/DATABASE_DESIGN.md §Principles). Drop order
    # is the reverse of creation: audit_logs and consent_grants reference tables above
    # them, and consent_requests is the ultimate parent, so it goes last.
    op.drop_index(op.f("ix_audit_logs_patient_id_occurred_at_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(
        op.f("ix_consent_grants_patient_id_grantee_doctor_id_category_id"),
        table_name="consent_grants",
    )
    op.drop_table("consent_grants")
    op.drop_table("consent_decisions")
    op.drop_table("consent_request_categories")
    op.drop_index(
        op.f("ix_consent_requests_requester_doctor_id_created_at_id"), table_name="consent_requests"
    )
    op.drop_index(
        op.f("ix_consent_requests_patient_id_created_at_id"), table_name="consent_requests"
    )
    op.drop_table("consent_requests")
