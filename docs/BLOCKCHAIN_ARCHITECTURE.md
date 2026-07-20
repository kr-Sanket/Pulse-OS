# Blockchain Architecture — Consent & Audit Anchoring

> Core decision: ADR-004. PostgreSQL is authoritative; the chain provides **tamper-evidence**,
> not storage. Hash-only, asynchronous, non-blocking. Built at M6 against an interface that
> exists from M3.

## What Goes On-Chain (and what never does)

| On-chain (Polygon Amoy) | Never on-chain |
|---|---|
| `keccak256` hash of the canonical event JSON | Any PHI or personal data, even encrypted |
| Event type code (CONSENT_GRANTED / CONSENT_REVOKED / RECORD_ACCESSED / …) | Health IDs, names, hospital IDs, filenames |
| Anchor timestamp (block time) | Record content or S3 keys |
| Opaque event UUID (random, unlinkable) | Anything enabling re-identification |

Rationale: public chain data is permanent and world-readable; hash-only keeps DPDP/GDPR erasure
satisfiable and removes all PHI-exposure risk while preserving the integrity property.

## Components

- **`AuditAnchor` interface** (consent module, M3): `anchor(event) -> receipt`,
  `verify(event, receipt) -> bool`. Implementations: `DbAuditAnchor` (M3, hash stored locally —
  used in dev/tests and as fallback), `PolygonAuditAnchor` (M6).
- **Smart contract** (Solidity, Hardhat, M6): minimal anchor registry —
  `recordAnchor(eventId, eventHash, eventType)` emitting an event; read function for
  verification. No business logic on-chain (consent *decisions* live in Postgres — putting
  decision logic on-chain would make revocation and privacy unmanageable). Contract is
  ownable/pausable; only the platform's anchoring wallet may write.
- **Anchoring worker** (ADR-008): consumes audit events from the queue, canonicalizes → hashes →
  submits tx → stores `AnchorReceipt` (tx hash, block, event hash) against the event row.
  Retries with backoff; a dead-letter status surfaces stuck anchors.
- **Reconciliation job** (`scripts/`): recomputes hashes for all audit rows, compares with
  on-chain anchors, reports (a) unanchored events older than a threshold, (b) hash mismatches =
  tampering detected. This job IS the RC-2 experiment.

## Failure Semantics (hard requirements)

1. Chain downtime **never blocks or delays** a consent decision or record access — anchoring is
   eventually consistent by design; the queue absorbs outages.
2. The demo works fully offline from the chain (DbAuditAnchor fallback), with anchoring shown
   when Amoy is healthy.
3. Testnet deprecation risk (Amoy is a testnet): all chain specifics (RPC URL, contract address,
   chain ID) are config; migrating testnets is an env change + redeploy of the contract.
4. Wallet key management: anchoring wallet private key is an env secret, never in code; it holds
   only worthless testnet MATIC.

## Verification Story (for the paper & demo)

Demo script: show a consent grant → its `AnchorReceipt` → the tx on the Amoy explorer → manually
tamper a copy of the audit row → run reconciliation → tampering flagged. Experiment for RC-2:
compare detection guarantees + overhead (latency, cost per event) vs a plain DB-log baseline.
