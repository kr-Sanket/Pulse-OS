# TODO.md — Actionable Task List

> Keep this short and current. Completed items move to SESSION.md history. 
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

## Blocked on Product Owner

- [ ] **Ops/validation items deferred by PO decision (2026-08-28)** — needed for the M0.3
      and M2 gate demos, not blocking implementation: install Docker + verify `make up`;
      run migrations + `scripts/seed.py` against real Postgres; live browser flow with a
      Firebase web config in `.env.local`; verify record upload lands in real MinIO.
- [ ] **Retrospectively sign off OD-1…3** — M3 shipped without them, running on the documented
      recommendations: OD-1 unclaimed patients NO; OD-2 grant expiry 90d, injected as a service
      default (`DEFAULT_GRANT_TTL`) and overridable per approval, not hard-coded; OD-3 grant
      exposes health profile — **not implemented either way**, so a ruling still changes code.
      See DOMAIN_MODEL.md §5.
- [ ] Review ADR-015 (self-registration + verification onboarding) and **ADR-016…019** (M3:
      records ⇄ consent dependency, return-not-raise for audited failures, `ACCESS_DENIED`,
      SHA-256 until keccak256) — all implemented per their documented rationale.
- [ ] Amend DOMAIN_MODEL.md §1: the audit action vocabulary there is now a strict subset of the
      implemented one (`ACCESS_DENIED` missing) — ADR-018.
- [ ] Resolve Review-1 deck conflict: Spring Boot + Synthea (slide 20) vs ADR-001 FastAPI +
      3-simulated-hospitals plan — amend ADRs or fix the slide (see SESSION.md session 005).
- [ ] Decide ADR-009 (deployment: Render vs AWS) — needed by M1 gate.
- [ ] Decide ADR-010 (Flutter timing) — needed by M1 gate.
- [ ] Confirm LLM provider + get API key (Gemini recommended per ADR-007) — needed by M5, key earlier for experiments.

## M0 — Foundation ✅ DONE

- M0.1 scaffold ✅ (2026-07-20, session 002) · M0.2 domain design ✅ (2026-07-20, session 003)
  · M0.3 walking skeleton ✅ (2026-08-28, sessions 008–012, merged as PR #1). Gate demo rides
  on the deferred PO ops items above.

## M2 — Backend Core ✅ DONE (2026-08-29, merged to `main`)

- [ ] ANY: small ops script to attach a *real* Firebase login as admin of a *seeded* hospital
      (set claims + insert HospitalAdmin row) — needed for a live portal demo (ADR-015 note).
- [ ] BE: **no code path provisions `Role.SYSTEM_ADMIN`**, so `POST /hospitals/{hid}/verify` has
      no reachable caller and self-registered hospitals are stranded `PENDING`. Masked in demos
      because the three simulated hospitals are seeded `VERIFIED`.
- [ ] BE: rate limiting middleware (Redis buckets; stricter on auth) — deferred since M0.3.
      **Now load-bearing:** see M3 findings below.
- [ ] BE: `ObjectStorage.put_object` sends no `ServerSideEncryption`; ADR-005 says
      "server-side encryption on". Unimplemented clause of an accepted ADR, on the PHI path.
- [ ] BE: `S3ObjectStorage._get_client()` builds the boto3 client lazily inside worker threads
      with no lock, unlike `FirebaseAuthProvider` which guards the identical pattern.

## M1 — Research & Design (parallel)

- [ ] ALL: Literature review — 3 papers each on HIE consent, blockchain audit, RAG summarization; notes into docs/.
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md) before any other screens.
- [ ] AI: Spike — Gemini free-tier limits vs expected summary/copilot volume; report findings.
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## M3 — Consent Domain (backend ✅ 2026-09-01, branch `feature/consent`)

- [x] BE: consent module — access request → per-category decision → grant → revoke;
      `consent.enforce()` on every non-owner record read; append-only `AuditLog`; migration 0004.
- [x] BE: records ⇄ consent integration, routers mounted, api-client regenerated (17 → 23 paths).
- [x] BE: merge-blocking review fixes — denied downloads now durably audited (M3-A); `is_hidden`
      enforced against consent reads (M3-C).
- [ ] ANY: **commit branch `feature/consent`** — only the schema (`a893611`) is committed; the
      repository, service, HTTP, integration, tests and these docs are not.

### Deferred M3 review findings (backend)

- [ ] BE: **M3-B** — `GET /records` returns full metadata (filenames, dates, descriptions) and
      writes **no** audit event. SYSTEM_ARCHITECTURE rule 3 covers "metadata-beyond-existence";
      CHECKLIST:26 requires an entry for every read. Either audit listings or amend the rule.
- [ ] BE: **M3-D** — `POST /access-requests` is an unthrottled Health-ID existence oracle
      (201 for a real ID, 422 for a fake one). SECURITY.md names rate limiting as the control.
      Must not survive into M7.
- [ ] BE: **M3-E** — hospital-admin denials are unaudited (layer 2 refuses before the choke
      point), while clinician denials are logged. Same family as the hidden-record refusal,
      which also writes nothing. One ruling should settle both.
- [ ] BE: **systemic** — no security event survives a failed request; ADR-017 treats the two
      read paths only. The durable fix (independent audit sink or outbox) needs its own ADR and
      changes DOMAIN_MODEL §1's same-transaction rule.
- [ ] BE: minors — `ConsentGrantRepository.list_page_by_patient` has no caller (a patient cannot
      list, therefore cannot revoke, a grant through any endpoint); N+1 on consent listings;
      `revokedAt` serialises naive on SQLite / aware on Postgres (API_GUIDELINES:28); records'
      read endpoints still declare only 200/422 in the spec; expiry sweep and the
      `(patient_id, status, …)` inbox index absent; `get_request_context` duplicated in two
      modules; three names for one concept (`ConsentRequest` / `/access-requests` /
      DOMAIN_MODEL's `AccessRequest`).

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-spec-driven contract tests between web client and backend (schemathesis).
- Synthetic medical record generator for realistic seed/eval data (needed by M5 evals).
- Content sniffing (magic bytes) on uploads — currently trusts the declared content type
  after allowlisting; revisit in the M7 security pass.
- Hide/unhide locker records — `is_hidden` column exists (0003); endpoint lands with the
  patient locker UI (M4).
