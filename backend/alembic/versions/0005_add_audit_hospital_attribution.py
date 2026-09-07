"""add historical hospital attribution and a hash scheme version to audit_logs (6b)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-07

ADR-023. Two columns and one index on the append-only ``audit_logs`` table; no existing row
is rewritten.

**``actor_hospital_id`` is nullable, and that is a domain fact, not laziness.** Patients
generate a large share of audit events — every consent decision, every revocation, every
read of their own records, every locker upload — and a patient belongs to no hospital.
NOT NULL would be unprovable.

**No backfill.** The only source for a legacy row's hospital is the actor's *current*
affiliation, and reading it would silently rewrite history whenever staff transfer: events
a doctor generated at hospital A would migrate into hospital B's audit view. Legacy rows
therefore keep ``actor_hospital_id IS NULL`` and are simply absent from hospital-scoped
queries — a documented blind spot, not a reconstructed one.

**``hash_version`` selects the whole hashing scheme** — canonicalization *and* algorithm
together, not two orthogonal columns (ADR-023 decision 1):

* v1 — the ten-key canonical payload of revision 0004, SHA-256. Rows written before this
  migration. Their key set does **not** contain ``actor_hospital_id``, which is exactly why
  their stored digests still reproduce: v1 canonicalization omits the key rather than
  emitting it as null.
* v2 — the same payload plus ``actor_hospital_id``, SHA-256. Rows written after it.
* v3 — reserved for ADR-019's keccak256 transition, which now has a mechanism to land in
  instead of invalidating the table.

``hash_version`` is deliberately **outside** the hashed payload. It cannot be abused: any
mis-selection is self-detecting, because recomputing a v2 row under v1 omits a key the
stored digest covered, and recomputing a v1 row under v2 adds one it did not.

Downgrade drops both columns and the index. It is reversible as schema, but note the
asymmetry: v1 rows still verify afterwards while v2 rows lose the attribution their digests
were computed over.
"""

import sqlalchemy as sa
from alembic import op


#: ``audit_logs`` exactly as revision 0004 created it.
#:
#: Batch mode normally reflects the table from a live connection, which offline (``--sql``)
#: mode has none of. Handing it the prior definition lets one migration file serve online
#: Postgres, online SQLite and offline generation alike. It must stay a literal snapshot of
#: 0004 — reusing the ORM model would describe the table *after* this migration and quietly
#: recreate it with the new columns already present.
def _audit_logs_table(*, with_0005: bool) -> sa.Table:
    """``audit_logs`` as a literal snapshot — before this migration, or after it.

    Batch mode normally reflects the table from a live connection, which offline (``--sql``)
    mode has none of. Handing it an explicit definition lets one migration file serve online
    Postgres, online SQLite and offline generation alike.

    It must stay a literal snapshot rather than reusing the ORM model: the model describes
    the table as it is *today*, so a future revision 0006 would silently make this migration
    recreate the table with 0006's columns in it.
    """
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("target_record_id", sa.Uuid(), nullable=True),
        sa.Column("target_category_id", sa.Uuid(), nullable=True),
        sa.Column("target_request_id", sa.Uuid(), nullable=True),
        sa.Column("request_context", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_audit_logs_users_actor_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name="fk_audit_logs_patients_patient_id"
        ),
        sa.ForeignKeyConstraint(
            ["target_record_id"],
            ["medical_records.id"],
            name="fk_audit_logs_medical_records_target_record_id",
        ),
        sa.ForeignKeyConstraint(
            ["target_category_id"],
            ["record_categories.id"],
            name="fk_audit_logs_record_categories_target_category_id",
        ),
        sa.ForeignKeyConstraint(
            ["target_request_id"],
            ["consent_requests.id"],
            name="fk_audit_logs_consent_requests_target_request_id",
        ),
        # Carried in copy_from because SQLite's copy-and-move drops the original table and
        # every index on it. Omitting it would leave the patient's audit view unindexed
        # after an upgrade, and would make 0004's downgrade fail on a missing index.
        sa.Index("ix_audit_logs_patient_id_occurred_at_id", "patient_id", "occurred_at", "id"),
    ]
    if with_0005:
        columns.extend(
            [
                sa.Column("actor_hospital_id", sa.Uuid(), nullable=True),
                sa.Column(
                    "hash_version",
                    sa.SmallInteger(),
                    server_default=sa.text("1"),
                    nullable=False,
                ),
                sa.ForeignKeyConstraint(
                    ["actor_hospital_id"],
                    ["hospitals.id"],
                    name="fk_audit_logs_actor_hospital_id_hospitals",
                ),
            ]
        )
    return sa.Table("audit_logs", sa.MetaData(), *columns)


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode because SQLite cannot ALTER a table to add a foreign key: it rewrites the
    # table copy-and-move, preserving every existing row and its digest. On Postgres it
    # emits the plain ALTERs. The test suite runs SQLite, production runs Postgres, and the
    # migration has to be the same file for both (revisions 0001-0004 never needed this
    # because they only ever created tables).
    with op.batch_alter_table("audit_logs", copy_from=_audit_logs_table(with_0005=False)) as batch:
        batch.add_column(sa.Column("actor_hospital_id", sa.Uuid(), nullable=True))
        # Server default so the column can be NOT NULL with no two-step backfill: every
        # existing row is v1 by definition, and the application sets it explicitly from here.
        batch.add_column(
            sa.Column(
                "hash_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False
            )
        )
        batch.create_foreign_key(
            batch.f("fk_audit_logs_actor_hospital_id_hospitals"),
            "hospitals",
            ["actor_hospital_id"],
            ["id"],
        )

    # The hospital audit view: one scope, keyset order over the event time — the same shape
    # as the patient index, which is left exactly as it was.
    op.create_index(
        op.f("ix_audit_logs_actor_hospital_id_occurred_at_id"),
        "audit_logs",
        ["actor_hospital_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_actor_hospital_id_occurred_at_id"), table_name="audit_logs")
    with op.batch_alter_table("audit_logs", copy_from=_audit_logs_table(with_0005=True)) as batch:
        batch.drop_constraint(
            batch.f("fk_audit_logs_actor_hospital_id_hospitals"), type_="foreignkey"
        )
        batch.drop_column("hash_version")
        batch.drop_column("actor_hospital_id")
