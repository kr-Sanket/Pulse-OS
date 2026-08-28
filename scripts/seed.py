"""Seed a PulseOS database with development/demo reference data. Idempotent.

Inserts the 3 simulated hospitals (HID-0001..0003) and the record-category vocabulary;
re-running any number of times never duplicates or mutates existing rows. All seeding
logic lives in the owning module (app/modules/records/seed.py) — this script only wires
the engine, session, and transaction from the application's own configuration.

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
    from app.modules.records.seed import seed_reference_data

    settings = get_settings()
    engine = create_db_engine(settings)
    try:
        factory = create_session_factory(engine)
        async with factory() as session, session.begin():
            result = await seed_reference_data(session)
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

    print(f"Hospitals created: {result.hospitals_created} (existing rows untouched)")
    print(f"Record categories created: {result.categories_created} (existing rows untouched)")
    if result.total_created == 0:
        print("Database already seeded — nothing to do.")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
