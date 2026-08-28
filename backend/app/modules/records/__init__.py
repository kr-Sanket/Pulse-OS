"""records module — medical-record metadata and its reference tables.

M0.3 scope: reference models only (``Hospital``, ``RecordCategory``) plus their
repositories and the idempotent seed logic consumed by scripts/seed.py. The
MedicalRecord itself (upload → S3, FHIR DocumentReference metadata, categorization)
arrives at M2 (.claude/ROADMAP.md). Isolation rules: docs/SYSTEM_ARCHITECTURE.md.
"""
