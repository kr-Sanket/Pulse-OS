# TODO.md — Actionable Task List

> Keep this short and current. Completed items move to SESSION.md history. 
> Owner codes: FE (frontend lead), BE (backend lead), AI (AI+blockchain lead), PO (product owner), ANY (whoever/Claude).

## Blocked on Product Owner

- [ ] **Ops/validation items deferred by PO decision (2026-08-28)** — needed for the M0.3
      and M2 gate demos, not blocking implementation: install Docker + verify `make up`;
      run migrations + `scripts/seed.py` against real Postgres; live browser flow with a
      Firebase web config in `.env.local`; verify record upload lands in real MinIO.
- [ ] Formally sign off OD-1 (unclaimed patients: recommend NO for MVP), OD-2 (grant expiry:
      recommend 90d adjustable), OD-3 (grant exposes health profile: recommend YES, explicit
      on consent screen) — see DOMAIN_MODEL.md §5. Needed before M3 consent implementation.
- [ ] Review ADR-015 (self-registration + verification onboarding for hospitals/doctors) —
      implemented at M2 per the documented rationale; flag any objection before M3 builds on it.
- [ ] Resolve Review-1 deck conflict: Spring Boot + Synthea (slide 20) vs ADR-001 FastAPI +
      3-simulated-hospitals plan — amend ADRs or fix the slide (see SESSION.md session 005).
- [ ] Decide ADR-009 (deployment: Render vs AWS) — needed by M1 gate.
- [ ] Decide ADR-010 (Flutter timing) — needed by M1 gate.
- [ ] Confirm LLM provider + get API key (Gemini recommended per ADR-007) — needed by M5, key earlier for experiments.

## M0 — Foundation ✅ DONE

- M0.1 scaffold ✅ (2026-07-20, session 002) · M0.2 domain design ✅ (2026-07-20, session 003)
  · M0.3 walking skeleton ✅ (2026-08-28, sessions 008–012, merged as PR #1). Gate demo rides
  on the deferred PO ops items above.

## M2 — Backend Core (code done 2026-08-29, session 013 — branch `feature/medical-records`)

- [x] BE: ADR-014 — arq chosen as the job queue; `core/queue.py` port (Arq + in-memory);
      worker entry point `arq app.workers.main.WorkerSettings`; no-op `record_uploaded` task.
- [x] BE: ADR-015 — onboarding flows; `records` org tables (Doctor, HospitalAdmin) +
      `MedicalRecord`, migration 0003; hospital register/verify; doctor register/activate/
      deactivate/list (cursor-paginated).
- [x] BE: record upload (multipart) → `ObjectStorage` port (S3/MinIO impl + fake), hospital
      + patient-locker flows; relationship-scoped list/get; presigned download URLs
      (M3 will insert `consent.enforce()` + audit ahead of these reads — doctors have NO
      record access until then, by design).
- [x] ANY: seed extended — demo admins + doctors per simulated hospital, 3 synthetic
      patients with pinned valid Health IDs; idempotency re-verified end to end.
- [x] ANY: api-client regenerated from the new OpenAPI spec; all web gates green.
- [ ] ANY: small ops script to attach a *real* Firebase login as admin of a *seeded* hospital
      (set claims + insert HospitalAdmin row) — needed for a live portal demo (ADR-015 note).
- [ ] BE: rate limiting middleware (Redis buckets; stricter on auth) — deferred since M0.3,
      fits when Redis is verified live (M2 gate ops or early M3).

## M1 — Research & Design (parallel)

- [ ] ALL: Literature review — 3 papers each on HIE consent, blockchain audit, RAG summarization; notes into docs/.
- [ ] FE: Figma — the 3 core journeys (CONTEXT.md) before any other screens.
- [ ] AI: Spike — Gemini free-tier limits vs expected summary/copilot volume; report findings.
- [ ] AI: Spike — EasyOCR vs Tesseract accuracy on 5 synthetic Indian lab-report PDFs.

## M3 — Consent Domain (next implementation milestone, after M2 gate + OD-1…3 sign-off)

- [ ] BE: consent module — AccessRequest → per-category ConsentDecision/ConsentGrant → revoke;
      `consent.enforce()` dependency wired into every record read; append-only AuditEvent
      (same-transaction); `AuditAnchor` interface + DB impl; notification fan-out stub.
- [ ] FE: doctor portal — search by Health ID, request access; patient portal — consent inbox,
      audit log view.

## Parking Lot (not now)

- Emergency QR security design (break-glass) — Phase 2, needs its own ADR.
- OpenAPI-spec-driven contract tests between web client and backend (schemathesis).
- Synthetic medical record generator for realistic seed/eval data (needed by M5 evals).
- Content sniffing (magic bytes) on uploads — currently trusts the declared content type
  after allowlisting; revisit in the M7 security pass.
- Hide/unhide locker records — `is_hidden` column exists (0003); endpoint lands with the
  patient locker UI (M4).
