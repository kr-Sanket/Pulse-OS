"""Seed a PulseOS database with development/demo reference data. Idempotent.

Inserts the 3 simulated hospitals (HID-0001..0003), the record-category vocabulary,
one demo admin + one demo doctor per hospital, and 3 synthetic patients with pinned
Health IDs; re-running any number of times never duplicates or mutates existing rows.
All seeding logic lives in the owning modules (records/seed.py, patients/seed.py,
auth/seed.py) — this script only wires the engine, session, and transaction from the
application's own configuration.

Run with the backend virtualenv's Python, after migrations:

    cd backend && .venv/bin/alembic upgrade head
    backend/.venv/bin/python scripts/seed.py     (from the repo root)
"""

import asyncio
import sys


async def run() -> int:
    from sqlalchemy.exc import DatabaseError

    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory
    from app.modules.patients.seed import seed_synthetic_patients
    from app.modules.records.seed import seed_demo_staff, seed_reference_data

    settings = get_settings()
    engine = create_db_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            reference = await seed_reference_data(session)
            staff = await seed_demo_staff(session)
            patients_created = await seed_synthetic_patients(session)
    except DatabaseError as exc:
        print(f"Seeding failed: {exc.orig or exc}", file=sys.stderr)
        print(
            "Is the database up and migrated? Try: make up && cd backend && "
            ".venv/bin/alembic upgrade head",
            file=sys.stderr,
        )
        return 1
    finally:
        await engine.dispose()

    print(f"Hospitals created: {reference.hospitals_created} (existing rows untouched)")
    print(f"Record categories created: {reference.categories_created} (existing rows untouched)")
    print(f"Hospital admins created: {staff.admins_created} (existing rows untouched)")
    print(f"Doctors created: {staff.doctors_created} (existing rows untouched)")
    print(f"Synthetic patients created: {patients_created} (existing rows untouched)")
    if reference.total_created + staff.total_created + patients_created == 0:
        print("Database already seeded — nothing to do.")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
