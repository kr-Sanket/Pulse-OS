#!/usr/bin/env python3
"""CLI entry point to seed the database with the 3 simulated hospitals and synthetic data.

Usage (from repo root):
    python scripts/seed.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.core.db import get_engine, get_session_factory  # noqa: E402
from app.core.seed import seed_database  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("seed-cli")


async def main() -> None:
    engine = get_engine()
    session_factory = get_session_factory(engine)
    logger.info("Connecting to database and running seed routine...")

    async with session_factory() as session:
        async with session.begin():
            summary = await seed_database(session)

    logger.info(
        "Finished seeding: %d categories, %d hospitals, %d doctors, %d patients created.",
        summary.categories_created,
        summary.hospitals_created,
        summary.doctors_created,
        summary.patients_created,
    )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
