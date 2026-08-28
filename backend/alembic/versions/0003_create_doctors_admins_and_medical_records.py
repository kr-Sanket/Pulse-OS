"""create doctors, hospital_admins and medical_records tables (M2 backend core)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

M2 physical schema (docs/DOMAIN_MODEL.md §1, ADR-015): the clinician and hospital-admin
profiles (1:1 with auth users, plain FKs across module boundaries) and the FHIR
DocumentReference-shaped record metadata. Enum-valued columns are plain VARCHAR
(non-native, no CHECK) as in revisions 0001/0002 — values enforced by the typed app layer.
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
        "doctors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("specialty", sa.String(length=80), nullable=True),
        sa.Column("registration_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doctors")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_doctors_users_user_id")),
        sa.ForeignKeyConstraint(
            ["hospital_id"], ["hospitals.id"], name=op.f("fk_doctors_hospitals_hospital_id")
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_doctors_user_id")),
    )
    op.create_index(op.f("ix_doctors_hospital_id"), "doctors", ["hospital_id"])

    op.create_table(
        "hospital_admins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hospital_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hospital_admins")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_hospital_admins_users_user_id")
        ),
        sa.ForeignKeyConstraint(
            ["hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_hospital_admins_hospitals_hospital_id"),
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_hospital_admins_user_id")),
    )
    op.create_index(op.f("ix_hospital_admins_hospital_id"), "hospital_admins", ["hospital_id"])

    op.create_table(
        "medical_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("patient_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("uploaded_by_hospital_id", sa.Uuid(), nullable=True),
        sa.Column("uploaded_by_doctor_id", sa.Uuid(), nullable=True),
        sa.Column("date_of_service", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("s3_key", sa.String(length=255), nullable=False),
        sa.Column("processing_status", sa.String(length=20), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_medical_records")),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name=op.f("fk_medical_records_patients_patient_id")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["record_categories.id"],
            name=op.f("fk_medical_records_record_categories_category_id"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_hospital_id"],
            ["hospitals.id"],
            name=op.f("fk_medical_records_hospitals_uploaded_by_hospital_id"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_doctor_id"],
            ["doctors.id"],
            name=op.f("fk_medical_records_doctors_uploaded_by_doctor_id"),
        ),
        sa.UniqueConstraint("s3_key", name=op.f("uq_medical_records_s3_key")),
    )
    op.create_index(op.f("ix_medical_records_patient_id"), "medical_records", ["patient_id"])
    op.create_index(
        op.f("ix_medical_records_uploaded_by_hospital_id"),
        "medical_records",
        ["uploaded_by_hospital_id"],
    )


def downgrade() -> None:
    # Every migration must be reversible (docs/DATABASE_DESIGN.md §Principles).
    op.drop_index(op.f("ix_medical_records_uploaded_by_hospital_id"), table_name="medical_records")
    op.drop_index(op.f("ix_medical_records_patient_id"), table_name="medical_records")
    op.drop_table("medical_records")
    op.drop_index(op.f("ix_hospital_admins_hospital_id"), table_name="hospital_admins")
    op.drop_table("hospital_admins")
    op.drop_index(op.f("ix_doctors_hospital_id"), table_name="doctors")
    op.drop_table("doctors")
