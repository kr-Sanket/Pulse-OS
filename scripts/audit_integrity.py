#!/usr/bin/env python3
"""Audit integrity verification CLI for PulseOS (ADR-027, M6.3).

Provides demonstrable, repeatable workflows for:
1. Sealing eligible unbatched v3 audit records into immutable Merkle batches.
2. Verifying sealed batches against stored Merkle roots and Keccak commitments.
3. Generating and independently verifying Merkle proofs for individual audit records.
4. Reconciling database audit records and detecting missing, modified, or inconsistent rows.

Supports human-readable terminal output and machine-readable JSON output (--json).
Zero PHI is included in Merkle leaves, root metadata, proofs, or CLI output.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _json_serial(obj: object) -> str:
    """JSON serializer for UUIDs, datetimes, and enums."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return str(obj.value)
    raise TypeError(f"Type {type(obj)} not serializable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PulseOS Audit Integrity Verification CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="output machine-readable JSON instead of formatted text",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # seal
    seal_parser = subparsers.add_parser(
        "seal",
        help="seal eligible unbatched v3 audit records into immutable Merkle batches",
    )
    seal_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of batches to seal (default: seal all available)",
    )

    # verify-batch
    verify_batch_parser = subparsers.add_parser(
        "verify-batch",
        help="verify a sealed batch against its stored Merkle root and member records",
    )
    batch_target = verify_batch_parser.add_mutually_exclusive_group(required=True)
    batch_target.add_argument(
        "--batch-number",
        type=int,
        help="sequential number of the batch to verify (e.g. 1)",
    )
    batch_target.add_argument(
        "--all",
        action="store_true",
        help="verify all sealed batches in the database sequentially",
    )

    # verify-event
    verify_event_parser = subparsers.add_parser(
        "verify-event",
        help="generate and verify a Merkle membership proof for an individual audit event",
    )
    verify_event_parser.add_argument(
        "--event-id",
        type=UUID,
        required=True,
        help="UUID of the audit log record to verify",
    )

    # reconcile
    subparsers.add_parser(
        "reconcile",
        help="reconcile all audit batches and events across the database to detect tampering",
    )

    return parser


async def _run_seal(
    service: object,
    session: object,
    limit: int | None,
    json_output: bool,
) -> int:
    from app.modules.consent.batch_service import AuditBatchService

    assert isinstance(service, AuditBatchService)

    sealed = await service.seal_all_batches(max_batches=limit)
    if hasattr(session, "commit"):
        await session.commit()

    if json_output:
        data = {
            "count": len(sealed),
            "sealed_batches": [
                {
                    "batch_number": b.batch_number,
                    "batch_id": str(b.id),
                    "leaf_count": b.leaf_count,
                    "root": b.root,
                    "commitment": b.commitment,
                    "first_occurred_at": b.first_occurred_at.isoformat(),
                    "last_occurred_at": b.last_occurred_at.isoformat(),
                }
                for b in sealed
            ],
        }
        print(json.dumps(data, indent=2))
        return 0

    if not sealed:
        print("No eligible unbatched v3 audit records to seal.")
        return 0

    print(f"=== Sealed {len(sealed)} Audit Batch{'es' if len(sealed) != 1 else ''} ===")
    for b in sealed:
        print(f"\nBatch #{b.batch_number} (ID: {b.id})")
        print(f"  Leaf Count:   {b.leaf_count}")
        print(f"  Root:         {b.root}")
        print(f"  Commitment:   {b.commitment}")
        print(
            f"  Time Span:    {b.first_occurred_at.isoformat()} -> {b.last_occurred_at.isoformat()}"
        )
    return 0


async def _run_verify_batch(
    service: object,
    batch_number: int | None,
    verify_all: bool,
    json_output: bool,
) -> int:
    from app.modules.consent.batch_service import AuditBatchService

    assert isinstance(service, AuditBatchService)

    batches_to_verify: list[int] = []
    if verify_all:
        all_batches = await service._batches.list_batches()
        batches_to_verify = [b.batch_number for b in all_batches]
        if not batches_to_verify:
            if json_output:
                print(json.dumps({"status": "NO_BATCHES", "batches": []}, indent=2))
            else:
                print("No sealed audit batches found in the database.")
            return 0
    else:
        assert batch_number is not None
        batches_to_verify = [batch_number]

    results: list[dict[str, Any]] = []
    all_valid = True

    for num in batches_to_verify:
        res = await service.verify_batch(num)
        if res is None:
            results.append(
                {
                    "batch_number": num,
                    "status": "NOT_FOUND",
                    "is_valid": False,
                    "error": f"Batch #{num} does not exist",
                    "findings": [],
                }
            )
            all_valid = False
            continue

        if not res.is_valid:
            all_valid = False

        results.append(
            {
                "batch_number": res.batch_number,
                "batch_id": str(res.batch_id),
                "protocol_version": res.protocol_version,
                "hash_version": res.hash_version,
                "leaf_count": res.leaf_count,
                "root": res.root,
                "commitment": res.commitment,
                "first_occurred_at": res.first_occurred_at.isoformat()
                if res.first_occurred_at
                else None,
                "last_occurred_at": res.last_occurred_at.isoformat()
                if res.last_occurred_at
                else None,
                "is_valid": res.is_valid,
                "status": "VALID" if res.is_valid else "TAMPERED",
                "findings": [
                    {
                        "kind": f.kind.value,
                        "batch_number": f.batch_number,
                        "audit_log_id": str(f.audit_log_id) if f.audit_log_id else None,
                    }
                    for f in res.findings
                ],
            }
        )

    if json_output:
        output_payload = (
            results[0]
            if (len(results) == 1 and not verify_all)
            else {
                "all_valid": all_valid,
                "batches_verified": len(results),
                "results": results,
            }
        )
        print(json.dumps(output_payload, indent=2))
        return 0 if all_valid else 1

    for r in results:
        print(f"\n=== Audit Batch Verification: Batch #{r['batch_number']} ===")
        if r.get("status") == "NOT_FOUND":
            print(f"Status:             [FAILED] {r.get('error')}")
            continue

        print(f"Batch ID:           {r['batch_id']}")
        print(f"Leaf Count:         {r['leaf_count']}")
        print(f"Protocol / Hash:    v{r['protocol_version']} / v{r['hash_version']}")
        print(f"Batch Root:         {r['root']}")
        print(f"Commitment:         {r['commitment']}")
        print(f"Time Range:         {r['first_occurred_at']} -> {r['last_occurred_at']}")
        if r["is_valid"]:
            print(
                "Status:             [OK] VALID (Merkle root, commitment, and all members intact)"
            )
        else:
            print("Status:             [FAILED] TAMPERED / INCONSISTENT")
            print("Findings:")
            for f in r["findings"]:
                loc = f" (batch #{f['batch_number']})" if f["batch_number"] is not None else ""
                evt = f" (event {f['audit_log_id']})" if f["audit_log_id"] is not None else ""
                print(f"  - {f['kind']}{loc}{evt}")

    return 0 if all_valid else 1


async def _run_verify_event(
    service: object,
    event_id: UUID,
    json_output: bool,
) -> int:
    from app.modules.consent.batch_service import AuditBatchService

    assert isinstance(service, AuditBatchService)

    result = await service.get_proof_for_event(event_id)
    if result is None:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "NOT_SEALED",
                        "audit_log_id": str(event_id),
                        "error": "Audit event is not sealed in any batch or does not exist",
                    },
                    indent=2,
                )
            )
        else:
            print(f"Event {event_id} is not sealed in any batch or does not exist.")
        return 1

    overall_valid = result.is_event_valid and result.is_proof_valid
    steps_payload = [
        {"sibling": s.sibling, "sibling_on_left": s.sibling_on_left} for s in result.proof.steps
    ]

    if json_output:
        print(
            json.dumps(
                {
                    "status": "VERIFIED" if overall_valid else "TAMPERED",
                    "audit_log_id": str(result.audit_log_id),
                    "batch_number": result.batch_number,
                    "batch_id": str(result.batch_id),
                    "leaf_index": result.leaf_index,
                    "leaf_count": result.leaf_count,
                    "event_digest": result.event_digest,
                    "recomputed_digest": result.recomputed_digest,
                    "root": result.root,
                    "commitment": result.commitment,
                    "is_event_valid": result.is_event_valid,
                    "is_proof_valid": result.is_proof_valid,
                    "proof_steps_count": result.proof_steps_count,
                    "proof": {
                        "leaf_index": result.proof.leaf_index,
                        "leaf_count": result.proof.leaf_count,
                        "steps": steps_payload,
                    },
                },
                indent=2,
            )
        )
        return 0 if overall_valid else 1

    print("\n=== Audit Event Merkle Verification ===")
    print(f"Audit Log ID:       {result.audit_log_id}")
    print(f"Batch Number:       #{result.batch_number} (ID: {result.batch_id})")
    print(f"Position:           Leaf {result.leaf_index} of {result.leaf_count}")
    print(f"Stored Digest:      {result.event_digest}")
    print(f"Recomputed Digest:  {result.recomputed_digest or '<missing or invalid>'}")
    if result.is_event_valid:
        print("Event Content:      [OK] VALID (row content matches stored digest)")
    else:
        print("Event Content:      [FAILED] TAMPERED (row content recomputed hash mismatch)")

    if result.is_proof_valid:
        print(f"Merkle Proof:       [OK] VALID ({result.proof_steps_count} steps verify to root)")
    else:
        print("Merkle Proof:       [FAILED] INVALID (proof does not verify against batch root)")

    print(f"Batch Root:         {result.root}")
    print(f"Batch Commitment:   {result.commitment}")
    print("Proof Steps:")
    for idx, step in enumerate(result.proof.steps):
        side = "left" if step.sibling_on_left else "right"
        print(f"  [{idx}] sibling: {step.sibling} ({side})")

    if overall_valid:
        print("Final Verdict:      [OK] VERIFIED")
    else:
        print("Final Verdict:      [FAILED] TAMPERED / INVALID")

    return 0 if overall_valid else 1


async def _run_reconcile(
    service: object,
    json_output: bool,
) -> int:
    from app.modules.consent.batch_service import AuditBatchService

    assert isinstance(service, AuditBatchService)

    report = await service.reconcile()

    findings_payload = [
        {
            "kind": f.kind.value,
            "batch_number": f.batch_number,
            "audit_log_id": str(f.audit_log_id) if f.audit_log_id else None,
        }
        for f in report.findings
    ]

    if json_output:
        print(
            json.dumps(
                {
                    "consistent": report.consistent,
                    "batches_checked": report.batches_checked,
                    "members_checked": report.members_checked,
                    "unbatched_v3_events": report.unbatched_v3_events,
                    "unbatched_events_checked": report.unbatched_events_checked,
                    "findings_count": len(report.findings),
                    "findings": findings_payload,
                },
                indent=2,
            )
        )
        return 0 if report.consistent else 1

    print("\n=== Audit Integrity Reconciliation Report ===")
    print(f"Batches Checked:          {report.batches_checked}")
    print(f"Batch Members Checked:    {report.members_checked}")
    print(f"Unbatched v3 Events:      {report.unbatched_v3_events}")
    print(f"Unbatched Events Checked: {report.unbatched_events_checked}")

    if report.consistent:
        print("Status:                   [OK] CONSISTENT (0 findings)")
    else:
        print(f"Status:                   [FAILED] INCONSISTENT ({len(report.findings)} findings)")
        print("Findings:")
        for f in findings_payload:
            loc = f" (batch #{f['batch_number']})" if f["batch_number"] is not None else ""
            evt = f" (event {f['audit_log_id']})" if f["audit_log_id"] is not None else ""
            print(f"  - {f['kind']}{loc}{evt}")

    return 0 if report.consistent else 1


async def run(
    args: argparse.Namespace,
    *,
    session_factory: Any = None,
    service: object | None = None,
) -> int:
    if service is not None:
        if args.command == "seal":
            return await _run_seal(service, None, args.limit, args.json_output)
        if args.command == "verify-batch":
            return await _run_verify_batch(service, args.batch_number, args.all, args.json_output)
        if args.command == "verify-event":
            return await _run_verify_event(service, args.event_id, args.json_output)
        if args.command == "reconcile":
            return await _run_reconcile(service, args.json_output)
        return 2

    from app.core.config import get_settings
    from app.core.db import create_db_engine, create_session_factory
    from app.modules.consent.dependencies import build_audit_batch_service

    settings = get_settings()
    engine = None
    factory = session_factory
    if factory is None:
        engine = create_db_engine(settings)
        factory = create_session_factory(engine)

    try:
        async with factory() as session:
            svc = build_audit_batch_service(session, settings)
            if args.command == "seal":
                return await _run_seal(svc, session, args.limit, args.json_output)
            if args.command == "verify-batch":
                return await _run_verify_batch(svc, args.batch_number, args.all, args.json_output)
            if args.command == "verify-event":
                return await _run_verify_event(svc, args.event_id, args.json_output)
            if args.command == "reconcile":
                return await _run_reconcile(svc, args.json_output)
            return 2
    finally:
        if engine is not None:
            await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        if getattr(args, "json_output", False):
            print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2), file=sys.stderr)
        else:
            print(f"Error executing audit integrity CLI: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
