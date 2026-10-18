"""Demonstrable audit integrity verification workflow tests (ADR-027, M6.3).

Tests sealing, verification, proof generation, tampering detection, concurrency,
zero-PHI guarantees, and CLI execution.
"""

import asyncio
import datetime as dt
import json
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.modules.auth.domain import Role
from app.modules.auth.models import User
from app.modules.consent.batch_service import (
    AuditBatchService,
    FindingKind,
)
from app.modules.consent.merkle import (
    verify_proof,
)
from app.modules.consent.models import (
    AuditAction,
    AuditBatchMember,
    AuditLog,
)
from app.modules.consent.repository import AuditBatchRepository
from app.modules.consent.service import (
    HASH_SCHEME_V3,
    recompute_event_hash,
)
from app.modules.patients.models import Patient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support import sqlite_session

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.audit_integrity as audit_integrity  # type: ignore[import-not-found] # noqa: E402

NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
BASE = NOW - dt.timedelta(hours=1)
BACKLOG = dt.timedelta(seconds=900)
PATIENT_HEALTH_ID = "PHI-IND-2026-TEST"
PATIENT_NAME = "Patient Test Audit"


def _run(scenario: Callable[..., Coroutine[Any, Any, None]]) -> None:
    asyncio.run(scenario())


class AuditTestHarness:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditBatchRepository(session)
        self.service = AuditBatchService(
            batches=self.repo,
            max_size=10,
            backlog_threshold=BACKLOG,
            clock=lambda: NOW,
        )
        self.user_id = uuid4()
        self.patient_id = uuid4()

    async def setup_entities(self) -> None:
        user = User(id=self.user_id, firebase_uid=f"fb-{uuid4()}", role=Role.PATIENT)
        self.session.add(user)
        await self.session.flush()
        patient = Patient(
            id=self.patient_id,
            user_id=user.id,
            health_id=PATIENT_HEALTH_ID,
            full_name=PATIENT_NAME,
        )
        self.session.add(patient)
        await self.session.flush()

    async def create_event(
        self,
        *,
        seconds: float,
        action: AuditAction = AuditAction.RECORD_VIEWED,
        scheme: int = HASH_SCHEME_V3,
    ) -> AuditLog:
        event = AuditLog(
            id=uuid4(),
            actor_user_id=self.user_id,
            actor_role=Role.PATIENT,
            action=action,
            patient_id=self.patient_id,
            request_context=None,
            occurred_at=BASE + dt.timedelta(seconds=seconds),
            actor_hospital_id=None,
            hash_version=scheme,
            event_hash="",
        )
        event.event_hash = recompute_event_hash(event)
        self.session.add(event)
        await self.session.flush()
        return event


def test_successful_sealing_and_verification() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            for i in range(5):
                await h.create_event(seconds=i * 10)

            sealed = await h.service.seal_all_batches()
            assert len(sealed) == 1
            batch = sealed[0]
            assert batch.batch_number == 1
            assert batch.leaf_count == 5

            result = await h.service.verify_batch(1)
            assert result is not None
            assert result.is_valid is True
            assert len(result.findings) == 0
            assert result.root == batch.root
            assert result.commitment == batch.commitment
            assert result.leaf_count == 5

    _run(scenario)


def test_repeated_sealing_idempotency() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            for i in range(3):
                await h.create_event(seconds=i * 10)

            first_sealed = await h.service.seal_all_batches()
            assert len(first_sealed) == 1

            # Repeated sealing when no unbatched events exist
            second_sealed = await h.service.seal_all_batches()
            assert len(second_sealed) == 0

            next_batch = await h.service.seal_next_batch()
            assert next_batch is None

            # Verify database still only has 1 batch
            batches = await h.repo.list_batches()
            assert len(batches) == 1

    _run(scenario)


def test_tampered_audit_event_content_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(4)]
            await h.service.seal_all_batches()

            # Tamper with an event's action column without recomputing event_hash
            tampered_event = events[2]
            tampered_event.action = AuditAction.RECORD_UPLOADED
            await session.flush()

            # Batch verification detects the tampering
            batch_res = await h.service.verify_batch(1)
            assert batch_res is not None
            assert batch_res.is_valid is False
            assert any(
                f.kind == FindingKind.MEMBER_DIGEST_MISMATCH and f.audit_log_id == tampered_event.id
                for f in batch_res.findings
            )

            # Event proof verification shows event row content is tampered
            proof_res = await h.service.get_proof_for_event(tampered_event.id)
            assert proof_res is not None
            assert proof_res.is_event_valid is False
            assert (
                proof_res.is_proof_valid is True
            )  # The sealed digest is in the tree, but row doesn't match

            # Reconciliation detects it
            report = await h.service.reconcile()
            assert not report.consistent
            assert any(f.kind == FindingKind.MEMBER_DIGEST_MISMATCH for f in report.findings)

    _run(scenario)


def test_tampered_event_hash_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(3)]
            await h.service.seal_all_batches()

            # Tamper directly with the stored event_hash
            events[1].event_hash = "deadbeef" * 8
            await session.flush()

            batch_res = await h.service.verify_batch(1)
            assert batch_res is not None
            assert batch_res.is_valid is False
            assert any(f.kind == FindingKind.MEMBER_DIGEST_MISMATCH for f in batch_res.findings)

            proof_res = await h.service.get_proof_for_event(events[1].id)
            assert proof_res is not None
            assert proof_res.is_event_valid is False

    _run(scenario)


def test_tampered_membership_digest_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(3)]
            sealed = await h.service.seal_all_batches()
            batch = sealed[0]

            # Tamper with the member row digest in audit_batch_members
            members = await h.repo.list_members_for_batch(batch.id)
            members[0].digest = "0123456789abcdef" * 4
            await session.flush()

            # Batch verification detects root mismatch
            batch_res = await h.service.verify_batch(1)
            assert batch_res is not None
            assert batch_res.is_valid is False
            assert FindingKind.ROOT_MISMATCH in {f.kind for f in batch_res.findings}

            # Proof verification against stored root fails
            proof_res = await h.service.get_proof_for_event(events[0].id)
            assert proof_res is not None
            assert proof_res.is_proof_valid is False

    _run(scenario)


class _MissingEventRepository(AuditBatchRepository):
    def __init__(self, session: AsyncSession, missing_id: UUID) -> None:
        super().__init__(session)
        self._missing_id = missing_id

    async def get_event_by_id(self, audit_log_id: UUID) -> AuditLog | None:
        if audit_log_id == self._missing_id:
            return None
        return await super().get_event_by_id(audit_log_id)

    async def list_members_with_events(
        self,
    ) -> list[tuple[AuditBatchMember, AuditLog | None]]:
        rows = await super().list_members_with_events()
        return [(m, None if m.audit_log_id == self._missing_id else e) for m, e in rows]

    async def list_members_with_events_for_batch(
        self, batch_id: UUID
    ) -> list[tuple[AuditBatchMember, AuditLog | None]]:
        rows = await super().list_members_with_events_for_batch(batch_id)
        return [(m, None if m.audit_log_id == self._missing_id else e) for m, e in rows]


def test_missing_event_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(3)]
            await h.service.seal_all_batches()

            missing_id = events[1].id
            missing_repo = _MissingEventRepository(session, missing_id)
            service_with_missing = AuditBatchService(
                batches=missing_repo,
                max_size=10,
                backlog_threshold=BACKLOG,
                clock=lambda: NOW,
            )

            batch_res = await service_with_missing.verify_batch(1)
            assert batch_res is not None
            assert batch_res.is_valid is False
            assert any(
                f.kind == FindingKind.MEMBER_EVENT_MISSING and f.audit_log_id == missing_id
                for f in batch_res.findings
            )

            proof_res = await service_with_missing.get_proof_for_event(missing_id)
            assert proof_res is not None
            assert proof_res.is_event_valid is False

            report = await service_with_missing.reconcile()
            assert not report.consistent
            assert any(
                f.kind == FindingKind.MEMBER_EVENT_MISSING and f.audit_log_id == missing_id
                for f in report.findings
            )

    _run(scenario)


def test_inconsistent_batch_metadata_detected() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            await h.create_event(seconds=10)
            sealed = await h.service.seal_all_batches()
            batch = sealed[0]

            # Inconsistent root
            batch.root = "feedface" * 8
            await session.flush()
            res = await h.service.verify_batch(1)
            assert res is not None
            assert res.is_valid is False
            assert FindingKind.ROOT_MISMATCH in {f.kind for f in res.findings}

            # Restore root and tamper with commitment
            batch.root = sealed[0].root
            batch.commitment = "badc0ffee0000000" * 4
            await session.flush()
            res = await h.service.verify_batch(1)
            assert res is not None
            assert res.is_valid is False
            assert FindingKind.COMMITMENT_MISMATCH in {f.kind for f in res.findings}

    _run(scenario)


def test_merkle_proof_generation_and_independent_verification() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(5)]
            sealed = await h.service.seal_all_batches()
            batch = sealed[0]

            for idx, event in enumerate(events):
                proof_res = await h.service.get_proof_for_event(event.id)
                assert proof_res is not None
                assert proof_res.audit_log_id == event.id
                assert proof_res.batch_number == 1
                assert proof_res.leaf_index == idx
                assert proof_res.leaf_count == 5
                assert proof_res.is_event_valid is True
                assert proof_res.is_proof_valid is True

                # Independent verification of the proof object
                assert verify_proof(
                    proof_res.event_digest,
                    proof_res.proof,
                    batch.root,
                    trusted_leaf_index=idx,
                    trusted_leaf_count=5,
                )

                # Forged digest fails
                assert not verify_proof(
                    "11112222" * 8,
                    proof_res.proof,
                    batch.root,
                    trusted_leaf_index=idx,
                    trusted_leaf_count=5,
                )

                # Forged root fails
                assert not verify_proof(
                    proof_res.event_digest,
                    proof_res.proof,
                    "99998888" * 8,
                    trusted_leaf_index=idx,
                    trusted_leaf_count=5,
                )

                # Wrong leaf index fails
                assert not verify_proof(
                    proof_res.event_digest,
                    proof_res.proof,
                    batch.root,
                    trusted_leaf_index=(idx + 1) % 5,
                    trusted_leaf_count=5,
                )

    _run(scenario)


def test_concurrent_sealing_conflict() -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            await h.create_event(seconds=10)
            await h.create_event(seconds=20)

            repo2 = AuditBatchRepository(session)
            service2 = AuditBatchService(
                batches=repo2, max_size=10, backlog_threshold=BACKLOG, clock=lambda: NOW
            )

            # Sealer 1 wins and seals
            batch1 = await h.service.seal_next_batch()
            assert batch1 is not None

            # Sealer 2 attempts to seal when events are already locked/batched
            batch2 = await service2.seal_next_batch()
            assert batch2 is None

    _run(scenario)


def test_zero_phi_in_integrity_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(3)]
            await h.service.seal_all_batches()

            # Check BatchVerificationResult
            batch_res = await h.service.verify_batch(1)
            assert batch_res is not None
            batch_repr = repr(batch_res)
            assert PATIENT_NAME not in batch_repr
            assert PATIENT_HEALTH_ID not in batch_repr

            # Check EventProofResult
            proof_res = await h.service.get_proof_for_event(events[0].id)
            assert proof_res is not None
            proof_repr = repr(proof_res)
            assert PATIENT_NAME not in proof_repr
            assert PATIENT_HEALTH_ID not in proof_repr

            # Check CLI JSON output
            parser = audit_integrity.build_parser()
            args = parser.parse_args(["--json", "verify-event", "--event-id", str(events[0].id)])
            exit_code = await audit_integrity.run(args, service=h.service)
            assert exit_code == 0
            captured = capsys.readouterr()
            json_out = captured.out
            assert PATIENT_NAME not in json_out
            assert PATIENT_HEALTH_ID not in json_out
            parsed = json.loads(json_out)
            assert parsed["status"] == "VERIFIED"

    _run(scenario)


def test_unverifiable_and_unsealed_records(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            # Non-existent batch
            res = await h.service.verify_batch(999)
            assert res is None

            # Non-existent event proof
            res_proof = await h.service.get_proof_for_event(uuid4())
            assert res_proof is None

            # Unbatched event proof
            unbatched = await h.create_event(seconds=10)
            res_unbatched = await h.service.get_proof_for_event(unbatched.id)
            assert res_unbatched is None

            # CLI behavior on non-existent batch
            parser = audit_integrity.build_parser()
            args = parser.parse_args(["verify-batch", "--batch-number", "999"])
            code = await audit_integrity.run(args, service=h.service)
            assert code == 1
            captured = capsys.readouterr()
            assert "Batch #999 does not exist" in captured.out

    _run(scenario)


def test_cli_full_workflow(capsys: pytest.CaptureFixture[str]) -> None:
    async def scenario() -> None:
        async with sqlite_session() as session:
            h = AuditTestHarness(session)
            await h.setup_entities()

            events = [await h.create_event(seconds=i * 10) for i in range(4)]

            parser = audit_integrity.build_parser()

            # 1. Seal CLI command
            args_seal = parser.parse_args(["seal"])
            code = await audit_integrity.run(args_seal, service=h.service)
            assert code == 0
            out_seal = capsys.readouterr().out
            assert "Sealed 1 Audit Batch" in out_seal
            assert "Batch #1" in out_seal

            # 2. Verify-batch CLI command (human-readable)
            args_vb = parser.parse_args(["verify-batch", "--batch-number", "1"])
            code = await audit_integrity.run(args_vb, service=h.service)
            assert code == 0
            out_vb = capsys.readouterr().out
            assert "[OK] VALID" in out_vb

            # 3. Verify-batch CLI command (--json)
            args_vb_json = parser.parse_args(["--json", "verify-batch", "--batch-number", "1"])
            code = await audit_integrity.run(args_vb_json, service=h.service)
            assert code == 0
            out_vb_json = json.loads(capsys.readouterr().out)
            assert out_vb_json["status"] == "VALID"
            assert out_vb_json["leaf_count"] == 4

            # 4. Verify-event CLI command (human-readable)
            args_ve = parser.parse_args(["verify-event", "--event-id", str(events[0].id)])
            code = await audit_integrity.run(args_ve, service=h.service)
            assert code == 0
            out_ve = capsys.readouterr().out
            assert "Final Verdict:      [OK] VERIFIED" in out_ve

            # 5. Reconcile CLI command
            args_rec = parser.parse_args(["reconcile"])
            code = await audit_integrity.run(args_rec, service=h.service)
            assert code == 0
            out_rec = capsys.readouterr().out
            assert "[OK] CONSISTENT" in out_rec

            # 6. Reconcile CLI command (--json)
            args_rec_json = parser.parse_args(["--json", "reconcile"])
            code = await audit_integrity.run(args_rec_json, service=h.service)
            assert code == 0
            out_rec_json = json.loads(capsys.readouterr().out)
            assert out_rec_json["consistent"] is True
            assert out_rec_json["batches_checked"] == 1

    _run(scenario)
