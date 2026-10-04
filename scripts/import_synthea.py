"""Import pinned Synthea FHIR R4 patients into PulseOS. Idempotent, non-destructive.

Turns bundles from the Synthea corpus into ordinary ``medical_records`` rows owned by
ordinary ``patients`` rows, so the portals show a realistic clinical history without any
special-case code. All logic lives in the owning module
(``app/modules/records/fhir_mapping.py`` + ``fhir_import.py``); this script only wires the
engine, the session, one transaction per bundle, and the report.

**The corpus is not in version control** (``.gitignore``: 1.3 GB, regenerable from the zip
or synthea.mitre.org), so this script is the one place that reads it and nothing in
``app/`` or the test suite depends on it being present.

Re-running is safe and does nothing: the patient is keyed on a derived
``synthetic:patient:synthea:{id}`` subject and every record on a UUIDv5, both behind UNIQUE
constraints. It inserts only — no row and no object is ever updated or deleted — and it
refuses to adopt a Health ID that already belongs to somebody else, so the three existing
demo patients cannot be affected.

Imported patients cannot authenticate, by design (``app/modules/auth/seed.py`` refuses
non-``synthetic:`` subjects). To sign in as one for a demo, link a real Firebase UID onto
it afterwards::

    backend/.venv/bin/python scripts/dev_link_identity.py \\
        --user-email joaquin141.rice937@synthea.pulseos.test \\
        --firebase-uid <your-firebase-uid>

Run from the repo root with the backend virtualenv's Python, after migrations and seeding
(the record-category vocabulary must exist first)::

    cd backend && .venv/bin/alembic upgrade head && cd ..
    backend/.venv/bin/python scripts/seed.py
    backend/.venv/bin/python scripts/import_synthea.py --patients 10
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE_DIR = REPO_ROOT / "FHIR_Dataset" / "fhir"

# The backend package is not installed; scripts/ runs against its source tree, exactly as
# scripts/dev_link_identity.py does.
sys.path.insert(0, str(REPO_ROOT / "backend"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import pinned Synthea patients into PulseOS (idempotent).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--patients",
        type=int,
        default=10,
        help="how many of the pinned roster to import, in order (default: 10)",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help=f"directory holding the Synthea bundles (default: {DEFAULT_BUNDLE_DIR})",
    )
    parser.add_argument(
        "--only",
        help="import a single roster entry by its bundle filename",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse, map and sanitize; write nothing to the database or object storage",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="show the pinned roster and exit",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy.exc import DatabaseError

    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory
    from app.modules.records.errors import StorageUnavailableError
    from app.modules.ai.ingestion import AIRecordIngestion
    from app.modules.ai.repository import AIRepository
    from app.modules.ai.service import AIIngestionService
    from app.modules.records.fhir_import import (
        SYNTHEA_DEMO_ROSTER,
        ImportRefused,
        SyntheaImporter,
    )
    from app.modules.records.fhir_mapping import (
        BundleInvalid,
        ProhibitedDataError,
        map_bundle,
        parse_bundle,
    )
    from app.modules.records.storage import S3ObjectStorage

    if args.list:
        print(f"Pinned Synthea demo roster ({len(SYNTHEA_DEMO_ROSTER)} patients):\n")
        for index, entry in enumerate(SYNTHEA_DEMO_ROSTER, start=1):
            marker = "  (canonical demo patient)" if index == 1 else ""
            print(f"  {index:2}. {entry.expected_name:26} {entry.health_id}{marker}")
            print(f"      {entry.email}")
        return 0

    selected = _select(SYNTHEA_DEMO_ROSTER, args)
    if selected is None:
        return 2
    if not args.bundle_dir.is_dir():
        print(f"Bundle directory not found: {args.bundle_dir}", file=sys.stderr)
        print(
            "The Synthea corpus is gitignored. Extract "
            "synthea_sample_data_fhir_r4_sep2019.zip into FHIR_Dataset/fhir/ first.",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    engine = create_db_engine(settings)
    storage = S3ObjectStorage(settings)
    factory = create_session_factory(engine)

    imported = 0
    patients_created = 0
    records_created = 0
    records_skipped = 0
    failures: list[tuple[str, str]] = []
    warnings_total = 0

    try:
        for entry in selected:
            path = args.bundle_dir / entry.filename
            if not path.is_file():
                failures.append((entry.filename, "bundle file not found"))
                continue
            raw = path.read_bytes()
            try:
                if args.dry_run:
                    mapping = map_bundle(parse_bundle(raw))
                    print(
                        f"  would import  {mapping.patient.full_name:26} "
                        f"{entry.health_id}  {len(mapping.records):4} records"
                    )
                    records_created += len(mapping.records)
                    warnings_total += len(mapping.warnings)
                    imported += 1
                    continue
                # One transaction per bundle: a bad bundle leaves nothing behind, and its
                # neighbours still import.
                async with factory() as session, session.begin():
                    ai_repository = AIRepository(session)
                    ai_service = AIIngestionService(ai_repository)
                    ai_ingestion = AIRecordIngestion(ai_service)

                    outcome = await SyntheaImporter(
                        session,
                        storage=storage,
                        ai_ingestion=ai_ingestion,
                    ).import_bundle(entry, raw)
            except (BundleInvalid, ImportRefused, ProhibitedDataError) as exc:
                # The filename and the reason only — never bundle content (docs/SECURITY.md).
                failures.append((entry.filename, f"{type(exc).__name__}: {exc}"))
                continue
            except StorageUnavailableError:
                failures.append((entry.filename, "object storage unavailable"))
                continue

            imported += 1
            patients_created += int(outcome.patient_created)
            records_created += outcome.records_created
            records_skipped += outcome.records_skipped
            warnings_total += len(outcome.warnings)
            state = "created" if outcome.patient_created else "existing"
            print(
                f"  {outcome.full_name:26} {outcome.health_id}  patient {state:8} "
                f"records +{outcome.records_created:<4} ={outcome.records_skipped}"
            )
    except DatabaseError as exc:
        print(f"Import failed: {exc.orig or exc}", file=sys.stderr)
        print(
            "Is the database up and migrated? Try: make up && cd backend && "
            ".venv/bin/alembic upgrade head",
            file=sys.stderr,
        )
        return 1
    finally:
        await engine.dispose()

    print()
    if args.dry_run:
        print(f"Dry run: {imported} bundles would import {records_created} records.")
    else:
        print(f"Bundles imported     : {imported}/{len(selected)}")
        print(f"Patients created     : {patients_created} (existing rows untouched)")
        print(f"Records created      : {records_created}")
        print(f"Records already there: {records_skipped}")
    if warnings_total:
        print(f"Non-fatal warnings   : {warnings_total} (unresolved refs / undatable resources)")
    if failures:
        print(f"\nSkipped {len(failures)} bundle(s):", file=sys.stderr)
        for filename, reason in failures:
            print(f"  {filename}: {reason}", file=sys.stderr)
    if imported == 0:
        print("\nNothing was imported.", file=sys.stderr)
        return 1
    return 0


def _select(roster: tuple[object, ...], args: argparse.Namespace) -> list[object] | None:
    """Which roster entries this run covers. Order is the roster's, so ``--patients 1``
    always means the canonical demo patient and never a different one."""
    if args.only is not None:
        matched = [entry for entry in roster if getattr(entry, "filename") == args.only]
        if not matched:
            print(
                f"{args.only!r} is not in the pinned roster. Use --list to see it.",
                file=sys.stderr,
            )
            return None
        return matched
    if args.patients < 1:
        print("--patients must be at least 1", file=sys.stderr)
        return None
    if args.patients > len(roster):
        print(
            f"--patients {args.patients} exceeds the pinned roster ({len(roster)}). "
            "Extending the demo set is a deliberate edit to SYNTHEA_DEMO_ROSTER.",
            file=sys.stderr,
        )
        return None
    return list(roster[: args.patients])


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
