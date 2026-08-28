"""create record_categories and medical_records tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

Physical schema for records' ``record_categories`` and ``medical_records``
(docs/DOMAIN_MODEL.md §1, reviewed against docs/DATABASE_DESIGN.md). Constraint
and index names follow the metadata naming convention in app/core/db.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "record_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_categories")),
        sa.UniqueConstraint("code", name=op.f("uq_record_categories_code")),
    )
    op.create_table(
        "medical_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(length=30), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=True),
        sa.Column("doctor_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medical_records")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_medical_records_record_categories_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["doctor_id"], ["doctors.id"], name=op.f("fk_medical_records_doctors_doctor_id")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_medical_records_hospitals_hospital_id"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.id"],
            name=op.f("fk_medical_records_patients_patient_id"),
        ),
    )
    op.create_index(
        op.f("ix_medical_records_category_id"), "medical_records", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_medical_records_doctor_id"), "medical_records", ["doctor_id"], unique=False
    )
    op.create_index(
        op.f("ix_medical_records_hospital_id"), "medical_records", ["hospital_id"], unique=False
    )
    op.create_index(
        op.f("ix_medical_records_patient_id"), "medical_records", ["patient_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_medical_records_patient_id"), table_name="medical_records")
    op.drop_index(op.f("ix_medical_records_hospital_id"), table_name="medical_records")
    op.drop_index(op.f("ix_medical_records_doctor_id"), table_name="medical_records")
    op.drop_index(op.f("ix_medical_records_category_id"), table_name="medical_records")
    op.drop_table("medical_records")
    op.drop_table("record_categories")
