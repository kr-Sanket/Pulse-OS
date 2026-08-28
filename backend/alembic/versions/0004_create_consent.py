"""create access_requests, consent_decisions, and consent_grants tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28

Physical schema for consent's ``access_requests``, ``access_request_categories``,
``consent_decisions``, and ``consent_grants`` (docs/DOMAIN_MODEL.md §1,
reviewed against docs/DATABASE_DESIGN.md). Constraint and index names follow
the metadata naming convention in app/core/db.py.
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
        "access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_requests")),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_access_requests_doctors_doctor_id")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_access_requests_hospitals_hospital_id"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_access_requests_patients_patient_id")
        ),
    )
    op.create_index(
        op.f("ix_access_requests_doctor_id"), "access_requests", ["doctor_id"], unique=False
    )
    op.create_index(
        op.f("ix_access_requests_hospital_id"), "access_requests", ["hospital_id"], unique=False
    )
    op.create_index(
        op.f("ix_access_requests_patient_id"), "access_requests", ["patient_id"], unique=False
    )

    op.create_table(
        "access_request_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_request_categories")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_access_request_categories_record_categories_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["access_requests.id"],
            name=op.f("fk_access_request_categories_access_requests_request_id"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "request_id",
            "category_id",
            name=op.f("uq_access_request_categories_request_id_category_id"),
        ),
    )
    op.create_index(
        op.f("ix_access_request_categories_category_id"),
        "access_request_categories",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_access_request_categories_request_id"),
        "access_request_categories",
        ["request_id"],
        unique=False,
    )

    op.create_table(
        "consent_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_decisions")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_consent_decisions_record_categories_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_consent_decisions_doctors_doctor_id")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_consent_decisions_patients_patient_id")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["access_requests.id"],
            name=op.f("fk_consent_decisions_access_requests_request_id"),
        ),
    )
    op.create_index(
        op.f("ix_consent_decisions_category_id"),
        "consent_decisions",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consent_decisions_doctor_id"), "consent_decisions", ["doctor_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_decisions_patient_id"), "consent_decisions", ["patient_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_decisions_request_id"), "consent_decisions", ["request_id"], unique=False
    )

    op.create_table(
        "consent_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("doctor_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
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
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_consent_grants_record_categories_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["consent_decisions.id"],
            name=op.f("fk_consent_grants_consent_decisions_decision_id"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_consent_grants_doctors_doctor_id")
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_consent_grants_patients_patient_id")
        ),
    )
    op.create_index(
        op.f("ix_consent_grants_category_id"), "consent_grants", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_grants_decision_id"), "consent_grants", ["decision_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_grants_doctor_id"), "consent_grants", ["doctor_id"], unique=False
    )
    op.create_index(
        op.f("ix_consent_grants_patient_id"), "consent_grants", ["patient_id"], unique=False
    )
    op.create_index(
        "ix_consent_grants_patient_doctor_category",
        "consent_grants",
        ["patient_id", "doctor_id", "category_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_consent_grants_patient_doctor_category", table_name="consent_grants")
    op.drop_index(op.f("ix_consent_grants_patient_id"), table_name="consent_grants")
    op.drop_index(op.f("ix_consent_grants_doctor_id"), table_name="consent_grants")
    op.drop_index(op.f("ix_consent_grants_decision_id"), table_name="consent_grants")
    op.drop_index(op.f("ix_consent_grants_category_id"), table_name="consent_grants")
    op.drop_table("consent_grants")

    op.drop_index(op.f("ix_consent_decisions_request_id"), table_name="consent_decisions")
    op.drop_index(op.f("ix_consent_decisions_patient_id"), table_name="consent_decisions")
    op.drop_index(op.f("ix_consent_decisions_doctor_id"), table_name="consent_decisions")
    op.drop_index(op.f("ix_consent_decisions_category_id"), table_name="consent_decisions")
    op.drop_table("consent_decisions")

    op.drop_index(
        op.f("ix_access_request_categories_request_id"), table_name="access_request_categories"
    )
    op.drop_index(
        op.f("ix_access_request_categories_category_id"), table_name="access_request_categories"
    )
    op.drop_table("access_request_categories")

    op.drop_index(op.f("ix_access_requests_patient_id"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_hospital_id"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_doctor_id"), table_name="access_requests")
    op.drop_table("access_requests")
