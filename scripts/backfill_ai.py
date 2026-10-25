"""Backfill the deterministic AI index from existing FHIR medical records.

Reads already-stored sanitized FHIR JSON from object storage and feeds it through
the same AI ingestion pipeline used by new Synthea imports.

Non-FHIR records are skipped by default. ``--uploads`` instead indexes uploaded PDFs that
have a text layer (records/upload_indexing.py: the same code the worker runs); images and
scanned PDFs are never indexed — there is no OCR.

This script is non-destructive:
- never modifies medical_records
- never deletes objects
- skips records already indexed in ai_documents
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

FHIR_CONTENT_TYPE = "application/fhir+json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill AI documents/chunks from existing FHIR records."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of FHIR records to inspect",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read and validate objects without writing AI rows",
    )
    parser.add_argument(
        "--uploads",
        action="store_true",
        help="index uploaded text-layer PDFs not yet indexed (instead of FHIR records)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="re-index records whose normalized content changed",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory

    # Register all ORM models on Base.metadata before AI models reference
    # cross-module foreign keys.
    from app.modules.patients import models as _patient_models  # noqa: F401
    from app.modules.records import models as _record_models  # noqa: F401
    from app.modules.ai import models as _ai_models  # noqa: F401

    from app.modules.ai.ingestion import AIRecordIngestion
    from app.modules.ai.repository import AIRepository
    from app.modules.ai.service import AIIngestionService
    from app.modules.records.errors import StorageUnavailableError
    from app.modules.records.models import MedicalRecord
    from app.modules.records.storage import S3ObjectStorage

    settings = get_settings()
    engine = create_db_engine(settings)
    factory = create_session_factory(engine)
    storage = S3ObjectStorage(settings)

    if args.uploads:
        if args.dry_run or args.reindex:
            print("--uploads does not support --dry-run or --reindex.", file=sys.stderr)
            await engine.dispose()
            return 2
        from app.modules.records.upload_indexing import backfill_uploaded_records

        try:
            counts = await backfill_uploaded_records(factory, storage, limit=args.limit)
        finally:
            await engine.dispose()
        for outcome, count in sorted(counts.items()):
            print(f"{outcome.value:<18}: {count}")
        return 0

    indexed = 0
    reindexed = 0
    already_indexed = 0
    empty = 0
    failures = 0

    try:
        async with factory() as session:
            query = (
                select(MedicalRecord)
                .where(MedicalRecord.content_type == FHIR_CONTENT_TYPE)
                .order_by(MedicalRecord.id)
            )

            if args.limit is not None:
                query = query.limit(args.limit)

            result = await session.execute(query)
            records = list(result.scalars())

        print(f"Found {len(records)} FHIR medical record(s).")

        for record in records:
            try:
                async with factory() as session, session.begin():
                    ai_repository = AIRepository(session)

                    existing = await ai_repository.get_document_by_record_id(record.id)

                    if existing is not None and not args.reindex:
                        already_indexed += 1
                        print(f"[skip] {record.id} already indexed")
                        continue

                    raw = await storage.get_object(record.s3_key)
                    resource = json.loads(raw)

                    if args.dry_run:
                        print(f"[dry-run] {record.id} {record.original_filename}")
                        continue

                    ai_service = AIIngestionService(ai_repository)
                    ai_ingestion = AIRecordIngestion(ai_service)

                    document = await ai_ingestion.index_fhir_resource(
                        record_id=record.id,
                        patient_id=record.patient_id,
                        category_id=record.category_id,
                        resource=resource,
                        reindex=args.reindex,
                    )

                    if document is None:
                        if existing is not None:
                            already_indexed += 1
                            print(f"[unchanged] {record.id}")
                        else:
                            empty += 1
                            print(f"[empty] {record.id}")
                    else:
                        if existing is not None:
                            reindexed += 1
                            print(f"[reindexed] {record.id} {record.original_filename}")
                        else:
                            indexed += 1
                            print(f"[indexed] {record.id} {record.original_filename}")

            except (StorageUnavailableError, json.JSONDecodeError, OSError) as exc:
                failures += 1
                print(
                    f"[failed] {record.id}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )

        print()
        print(f"FHIR records inspected : {len(records)}")
        print(f"Indexed                : {indexed}")
        print(f"Reindexed              : {reindexed}")
        print(f"Already indexed        : {already_indexed}")
        print(f"Empty                  : {empty}")
        print(f"Failures               : {failures}")
        print("Non-FHIR records       : skipped by content-type filter")

    finally:
        await engine.dispose()

    return 1 if failures else 0


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
