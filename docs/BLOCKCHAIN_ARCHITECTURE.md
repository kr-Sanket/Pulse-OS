# Blockchain Architecture — Consent & Audit Anchoring

> Core decisions: ADR-004 (hash-only, asynchronous, non-blocking; decision 2 amended) and
> **ADR-027** (Merkle-batched anchoring of verified v3 audit events). PostgreSQL is authoritative;
> the chain provides **tamper-evidence**, not storage. Built at M6 against an interface that
> exists from M3.

## What Goes On-Chain (and what never does)

| On-chain (Polygon Amoy) | Never on-chain |
|---|---|
| One opaque 32-byte **batch commitment** `C` per Merkle batch (ADR-027 decision 5) | Any PHI or personal data, even encrypted |
| One minimal registry event carrying `C` | Patient IDs, Health IDs, names, hospital IDs, filenames |
| Observable by anyone, unavoidably: sender address, block time, inclusion | Event UUIDs, event types, raw audit records |
| | Per-event digests, leaf hashes, Merkle roots, record content, S3 keys |

`C = keccak256(0x02 ‖ uint8 protocol_version ‖ uint64 batch_number ‖ uint32 leaf_count ‖ bytes32 root)`,
packed and big-endian (Solidity: `keccak256(abi.encodePacked(bytes1(0x02), uint8(v), uint64(n),
uint32(c), root))`). Public sender and timing reveal the platform's anchoring cadence, not who or
what was involved.

Rationale: public chain data is permanent and world-readable; hash-only keeps DPDP/GDPR erasure
satisfiable and removes all PHI-exposure risk while preserving the integrity property. One
commitment per batch, rather than per event, also stops the chain from revealing the timing and
type of individual patients' care (ADR-027).

**Hash versions (ADR-019, ADR-023).** Each audit row's `hash_version` selects its canonical payload
and algorithm. Only **v3** rows carry a Keccak-256 digest, and new events are written under v3.
v1/v2 rows predate the keccak transition and carry SHA-256 digests that stay verifiable locally
but are never batched or anchored on-chain. Only verified v3 events (`V3Batch`: valid UUID id,
`hash_version == 3`, digest recomputes) may enter a batch.

## Merkle Protocol v1 (reference: `backend/app/modules/consent/merkle.py`)

- Keccak-256 throughout (never SHA3-256). Leaf `keccak256(0x00 ‖ d)` over the event digest's 32 raw
  bytes; node `keccak256(0x01 ‖ left ‖ right)`; children positional, not sorted.
- An unpaired last node is promoted unchanged (never duplicated) — equivalent to RFC 6962.
- Empty batches refused; single-leaf root is `keccak256(0x00 ‖ d)`; duplicates refused.
- Leaves ordered `(occurred_at UTC ASC, id ASC)` once at sealing; the persisted `leaf_index` is
  authoritative thereafter.
- A proof establishes membership only. Index and batch size are authoritative only from persisted
  batch metadata (`trusted_leaf_index` / `trusted_leaf_count`); no proof establishes completeness.
- The pinned vectors in `test_audit_merkle.py` and the commitment vectors in ADR-027 must be
  reproduced byte for byte by any other implementation, including the contract.

## Components

Status as of 2026-10-11: **built** — the port, the local adapter, migration 0006, v3 hashing,
`merkle.py`. **M6.3, committed in `e3c0fe1` (PostgreSQL integration tests in `1ce4c14`);
M6.1–M6.3 accepted with deferred items** — batch persistence (migration 0007), sealing,
commitments, database-only reconciliation; reported validation: full backend run 1045 passed,
2 skipped, with the 2 opt-in PostgreSQL tests and a manual migration check reported passing
against a disposable scratch database (historical results). **Deferred** — everything
chain-facing: on-chain batch submission, receipts, chain-side verification. The M6 gate is not
complete; M6.4 is not authorized.

- **`AuditAnchor` interface** (`consent/anchoring.py`, built): `submit(digest) -> AnchorReceipt`,
  `verify(digest, receipt) -> bool` — only a bare 64-hex value crosses it (`require_digest`). Under
  ADR-027 the value submitted is a batch commitment `C`, so the port is unchanged.
  Implementations: `LocalChainAuditAnchor` (built — network-free, used in dev/tests and as
  fallback; a simulation with no independent immutability), `PolygonAuditAnchor` (deferred).
- **Per-event anchors** (`audit_anchors`, migration 0006, built): historical rows stay readable and
  are never rewritten. Since batch sealing (M6.3), the per-event workflow no longer admits v3
  events; a v3 event's *batch* anchoring status comes from its batch, not a per-event row.
  Historical per-event anchors (including any v3 ones written before M6.3) still verify, but only
  as historical per-event evidence — never as proof of batch membership or of on-chain commitment
  verification (ADR-027 decision 7).
- **Batch sealing** (M6.3): asynchronous and never on a request path. Selects unbatched v3 events
  in canonical order up to a configurable maximum (initially 256), builds a `V3Batch`, assigns the
  next contiguous `batch_number`, computes `C`, and writes the immutable batch and membership rows
  in one transaction. Initial sealing interval 300 s, configurable; the scheduler is deferred.
  UNIQUE `batch_number` and UNIQUE per-event membership make concurrent sealing safe.
- **Receipts and submission** (deferred): append-only receipt per batch and network (tx hash,
  block, time). Submission is retry-safe: check whether `C` is already on-chain before resending.
- **Smart contract** (Solidity, deferred): a minimal write-restricted registry of commitments that
  emits one event carrying `C`. No business logic on-chain (consent *decisions* live in Postgres —
  putting decision logic on-chain would make revocation and privacy unmanageable). Must use
  `abi.encodePacked` exactly as above; must **not** use OpenZeppelin `MerkleProof` /
  `StandardMerkleTree` (sorted pairs, no node prefix — incompatible); any on-chain proof check must
  handle promoted nodes and reject `leafCount == 0` / `leafIndex >= leafCount`.
- **Reconciliation** (database-only library at M6.3; CLI and chain-side checks deferred): reports
  v3 events unbatched beyond the backlog threshold (initially 900 s), per-batch membership
  integrity (count, contiguous indices, rows recompute to sealed digests, root and `C` rebuild),
  `batch_number` gaps, backdated (late-arriving) events, and unbatched events of any version that
  do not recompute under their own stored version (`EVENT_DIGEST_MISMATCH`) or carry an unsupported
  one (`UNSUPPORTED_HASH_VERSION`). Chain-side: stored `C` vs on-chain value, orphaned on-chain
  commitments. This job IS the RC-2 experiment. It never claims a Merkle proof establishes
  completeness. Accepted limitations, both bounded by the sealing interval: an event deleted before
  sealing leaves no trace, and one relabelled with a consistently rewritten digest before sealing
  is indistinguishable from a genuine event of that version (database-level append-only
  enforcement is deferred to M7).
- **Verdicts:** integrity verdicts are computed on demand; batches, memberships and receipts are
  persisted *evidence*, never a mutable status.

## Failure Semantics (hard requirements)

1. Chain downtime **never blocks or delays** a consent decision or record access — sealing and
   submission are asynchronous and eventually consistent; sealed batches wait for submission.
2. The demo works fully offline from the chain (`LocalChainAuditAnchor` fallback), with anchoring
   shown when Amoy is healthy.
3. Testnet deprecation risk (Amoy is a testnet): all chain specifics (RPC URL, contract address,
   chain ID) are config; migrating testnets is an env change + redeploy of the contract.
4. Wallet key management: anchoring wallet private key is an env secret, never in code; it holds
   only worthless testnet MATIC.

## Verification Story (for the paper & demo)

Demo script: show a consent grant → its batch membership and leaf index → the batch commitment and
its receipt → the tx on the Amoy explorer → manually tamper a copy of the audit row → run
reconciliation → tampering flagged. Experiment for RC-2: compare detection guarantees + overhead
(latency, cost per event amortised over a batch) vs a plain DB-log baseline.
