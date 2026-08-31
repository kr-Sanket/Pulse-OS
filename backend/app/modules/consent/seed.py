"""consent seed data — none required.

The consent granularity unit is ``RecordCategory``, which belongs to ``records`` and is
already seeded there (docs/DOMAIN_MODEL.md §1). This module owns no controlled vocabulary
and no reference rows, so a freshly migrated database needs nothing from here in order to
work; ``scripts/seed.py`` is deliberately not wired to this file.

The file exists for one anticipated use: demo access requests, decisions, and grants
between the seeded synthetic patients and the demo doctors, so the M3 gate flow is
reproducible without clicking through both portals. If that is built it follows the house
rules — idempotent by construction, keyed on business identifiers, existing rows never
mutated, and clearly synthetic (.claude/CLAUDE.md hard rules).
"""
