# Demo Guide

> A presenter's script for the final review. It describes only what exists on `main` and was
> checked against the code and the backend HTTP tests on 2026-10-26. All data is synthetic:
> never upload a real document. Setup details live in [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
> and [scripts/README.md](../scripts/README.md); this guide does not repeat them.

Each workflow below is also pinned by one backend test that runs the whole sequence over HTTP
against the real application, with only auth, object storage, the queue and the LLM faked:

| Workflow | Test |
|---|---|
| C: patient-controlled sharing | `backend/tests/test_demo_sharing_workflow.py` |
| D: AI record assistant | `backend/tests/test_demo_ai_workflow.py` |

Run `cd backend && .venv/bin/pytest -p no:cacheprovider tests/test_demo_sharing_workflow.py tests/test_demo_ai_workflow.py`
before a demo. If they pass, the backend behaviour this script relies on is intact.

## 1. Start the stack

From the repo root, one terminal per long-running process:

```bash
make up                                   # PostgreSQL (host port 5433), Redis, MinIO
cd backend && .venv/bin/alembic upgrade head && cd ..
backend/.venv/bin/python scripts/seed.py  # idempotent: 3 hospitals, 13 categories, demo staff, 3 patients

make dev-api                              # FastAPI on http://localhost:8000
cd backend && .venv/bin/arq app.workers.main.WorkerSettings   # the upload-indexing worker (workflow D)
ollama serve                              # and once: ollama pull qwen3:8b (the default model)
make dev-patient                          # http://localhost:5173
make dev-doctor                           # http://localhost:5174
```

- **The worker is required for workflow D.** Without it, uploads succeed but stay "Not yet
  indexed for AI search" forever. PDFs uploaded while it was down can be indexed later with
  `backend/.venv/bin/python scripts/backfill_ai.py --uploads`.
- **Ollama.** The API calls a local Ollama at `PULSEOS_OLLAMA_BASE_URL` (default
  `http://localhost:11434`) with `PULSEOS_OLLAMA_MODEL` (default `qwen3:8b`). If it is down, the
  assistant shows "Local AI service (Ollama) is unavailable…" (503). As a fallback for a rehearsal
  with no model, set `PULSEOS_AI_PROVIDER=fake` in `backend/.env`. The fake answers
  "Based on the available evidence [1]." and the badge reads `fake / fake-v1`. Say so if you use it.
- **Sign-in needs Firebase.** The portals sign in with Firebase (`web/apps/*/.env.local`; the
  API needs `PULSEOS_FIREBASE_CREDENTIALS_FILE` or Application Default Credentials). The dev-build
  mock user that runs without Firebase is for UI work only: the real API rejects its token.

### Demo identities

Link two real Google accounts onto seeded rows (local DB only; see scripts/README.md for the
re-seeding caveat):

```bash
backend/.venv/bin/python scripts/dev_link_identity.py --list
backend/.venv/bin/python scripts/dev_link_identity.py --user-email aarav@demo.pulseos.test   --firebase-uid <PATIENT_UID>
backend/.venv/bin/python scripts/dev_link_identity.py --user-email dr.george@demo.pulseos.test --firebase-uid <DOCTOR_UID>
```

| Role | Seeded row | Portal |
|---|---|---|
| Patient | Aarav Sharma (Demo), `PHI-IND-2026-1QE8DVR` | patient, :5173 |
| Doctor | Dr. Thomas George (Demo), CMC Vellore, seeded ACTIVE | doctor, :5174 |

Optional, for a richer FHIR export: `scripts/import_synthea.py --patients N` imports Synthea
patients with structured FHIR records. It needs the git-ignored `FHIR_Dataset/` corpus. Link a
Google account to one of them the same way (`--user-email <name>@synthea.pulseos.test`). Aarav
has no structured FHIR records, so his export contains only the Patient resource.

### Synthetic PDFs

Upload accepts PDF, JPEG and PNG, up to 15 MB. Build two synthetic PDFs with the test helper,
which writes no binaries into the repo:

```bash
mkdir -p /tmp/pulseos-demo && cd backend && .venv/bin/python -c "
from tests.pdf_fixtures import text_pdf, blank_pdf
open('/tmp/pulseos-demo/ferritin-demo.pdf','wb').write(text_pdf([
    'SYNTHETIC DEMO LAB REPORT - not a real patient',
    'Haemoglobin 9.8 g/dL (low)',
    'Serum ferritin 8 ng/mL (markedly low)',
    'Impression: iron deficiency anaemia']))
open('/tmp/pulseos-demo/scanned-demo.pdf','wb').write(blank_pdf())   # no text layer, like a scan
"
```

Any PDF you export from a word processor also has a text layer. A photographed or scanned
page does not.

## Workflow C: patient-controlled sharing

| # | Who / where | Action | What the screen shows |
|---|---|---|---|
| 1 | Patient → **My Records** | **Upload Record**: `ferritin-demo.pdf`, category *Lab Report*, a past date | The record appears and opens in the details panel. Hospital: "Added by the patient". |
| 2 | Doctor → **Find a Patient** | Search `PHI-IND-2026-1QE8DVR` | Category names only (e.g. *Lab Report*). The doctor sees that records exist but cannot open them. |
| 3 | Doctor | Select *Lab Report* (and, to show a per-category decision, another listed category) → **Request Access** with a purpose | The request appears under **My Requests** as pending. |
| 4 | Patient → **Consent Requests** | Approve *Lab Report*, Decline the other category, submit | The request moves to decided. **Active Grants** lists Dr. Thomas George / CMC Vellore with *Lab Report*. |
| 5 | Doctor → **Find a Patient** → **View Granted Records** | Open the PDF record → **Download** | Granted records list *Lab Report* records only. The record detail shows the file name, size and AI status badge. Download opens a short-lived MinIO URL. The declined category is not listed. |
| 6 | Patient → **My Records** → **Export FHIR (JSON)** (optional) | Download the bundle | An `application/fhir+json` collection Bundle of the patient's structured records. Uploaded files (PDF/JPEG/PNG) are never embedded. |
| 7 | Patient → **Active Grants** | **Revoke Access** → confirm | The grant leaves the active list. |
| 8 | Doctor | Reload the record page or the granted list | The record page says "This record is not available to you. The patient may have withdrawn your access…". The granted list says "No access granted yet". Revocation takes effect on the next request. |
| 9 | Patient → **Audit History** | (Optional) turn on **Show my activity** to include the patient's own views and downloads | Entries such as *Uploaded*, *Access requested*, *Consent approved*, *Consent declined*, *Records listed*, *Viewed*, *Downloaded*, *Access withdrawn*, *Access denied*, each naming the clinician and hospital. |

Things to say while presenting:

- Approving two categories creates two grants, so the trail shows one *Consent approved* per
  approved category and one *Access withdrawn* per revoked grant.
- A refused read is a 404 to the clinician, the same answer as for a record that does not exist.
  It still lands on the patient's trail as *Access denied*.
- **Clinician FHIR export has no doctor-portal button. It is API-only:**
  `GET /api/v1/records/export/fhir?patientHealthId=PHI-IND-2026-1QE8DVR` with the doctor's bearer
  token (copy it from a request in the browser's network tab). With a grant, it returns only the
  granted categories. Without one (or after revoking), it returns 403 and writes *Access denied*.
  The bundle is FHIR R4-shaped and has not been HL7-validated.
- Hiding a record (patient record panel → **Hide from doctors**) removes it from every clinician path while the
  grant stays in place. Hiding is a separate control from revocation.

## Workflow D: AI record assistant

| # | Who / where | Action | What the screen shows |
|---|---|---|---|
| 1 | Patient → **My Records** | Upload `ferritin-demo.pdf` (*Lab Report*) and `scanned-demo.pdf` | Both open with **AI search**: "Not yet indexed for AI search." |
| 2 | (worker) | Wait a few seconds, then **reload the page** and reopen each record | Text PDF: "Its text is searchable by your Health Copilot and, only within consent you grant, by a clinician's AI assistant." Scan: "Not searchable by AI: no readable text was found (a scanned, encrypted or damaged PDF)." A JPEG/PNG says images would need OCR, which PulseOS does not support. |
| 3 | Patient → **PulseOS Health Copilot** panel (on My Records) | Ask "What was my serum ferritin?" | An answer with `[1]`-style markers, a **Cited Records** row of badges (e.g. `[1] LAB_REPORT`), the provider/model badge and the disclaimer. Clicking a badge selects that record. |
| 4 | Doctor (with a *Lab Report* grant, from workflow C steps 2–5) → **View Granted Records** | Ask the **Clinical AI Assistant** the same question | The same evidence, cited. The doctor's record page shows the badge "Indexed for AI search". |
| 5 | Patient | **Hide from doctors** on the PDF, and the doctor asks again | "No matching clinical evidence found" with the fixed sentence "The available medical records do not contain information regarding the requested topic." The patient's own copilot still cites the PDF. |
| 6 | Patient | Revoke the grant | The doctor's granted page loses its records, and the assistant panel is shown only while granted records are listed. |
| 7 | Patient → **Audit History** | | *Summary generated* for each delivered answer. Clinician answers with no live grant appear as *Access denied*. |

What the backend guarantees, and what the test pins:

- **Citations match the text.** Every `[N]` left in the answer names an evidence chunk that was
  actually supplied, and every returned citation appears as a marker in the text. Markers that
  name nothing are removed, and citations are rebuilt from the evidence, never from
  model-supplied record ids. Whether a sentence is *supported* by the cited chunk is not checked
  (keep the disclaimer in view).
- **If the model cites nothing,** both panels label the answer "Answer without citations" with
  a note to verify it, instead of "no matching records".
- **Consent is re-checked after generation.** If the grant is revoked while the model is
  answering, the answer and citations are discarded, the doctor gets the no-evidence sentence,
  and *Access denied* is recorded instead of *Summary generated*.
- Scope is decided in SQL before retrieval: granted categories only, hidden records excluded
  for clinicians, read live (no re-index after hide/unhide or revoke).

## Known limitations (say them, do not demo around them)

- **No OCR.** Images and scanned PDFs are stored but never searchable. Text extraction is capped
  at 300 pages / 500,000 characters per PDF. A PDF with no text, an encrypted PDF or a damaged PDF
  ends `FAILED` and is not retried.
- **Retrieval is lexical** (term substring matching plus a fixed clinical-synonym table). It
  uses no embeddings, so a question must share words with the document.
- **Status does not refresh live.** After upload, reload the page to see the indexing result.
- Answers come from a local model and can be wrong. Nothing is sent to a hosted LLM. Evidence
  text is not redacted before it reaches the Ollama host.
- An answer whose granted scope matched nothing is not audited, because nothing was read. An
  operational failure (Ollama down or timed out) is not audited either.
- FHIR export includes structured FHIR records only. It is not HL7-validated, and there is no
  doctor-portal export button.
- There is no end-to-end browser test suite. The cross-portal flows are covered by the backend
  HTTP tests named above and by this manual walk-through.

## Hospital lifecycle (System Admin)

ADR-034 (accepted; uncommitted working tree). Needs a SYSTEM_ADMIN account
(`scripts/dev_provision_system_admin.py --firebase-uid <real uid>`) and the hospital portal.

| Step | Action | What to show |
|---|---|---|
| 1 | Sign in to the hospital portal as SYSTEM_ADMIN | Hospital verification view with status filter |
| 2 | Pick a PENDING hospital → Verify (optional reason) | Badge becomes Verified; History panel shows a VERIFIED event with actor and time |
| 3 | Suspend it with a reason | Badge Suspended; History adds SUSPENDED + reason |
| 4 | As that hospital's admin, try an upload or Health-ID lookup | Refused (409). Existing consented doctor access still works — suspension does not rewrite consent |
| 4b | As that hospital's doctor, send a new access request | Refused (409, "not verified"); reading an already-granted record still works |
| 5 | Reinstate | Badge Verified; REINSTATED event; original verifier/time kept |
| 6 | Reject a different PENDING hospital, then try Verify on it | 409 — rejection is terminal |
| 7 | Repeat an action whose target already holds (e.g. Suspend twice) | 200, no new history row |

Transition matrix: `.claude/DECISIONS.md` ADR-034. Coverage: `tests/test_organizations_http.py`,
`tests/test_organizations_service.py`, `tests/test_m3_gate.py` (suspension vs consent),
`tests/test_hospital_lifecycle_postgres.py` (row locks, rollback; opt-in PostgreSQL).

## Audit integrity and blockchain anchoring

ADR-027 (local Merkle batches, built) + ADR-035 (public-chain anchoring, proposed; implemented,
verified on a local EVM only). **Say clearly which layer each screen shows.**

**Without any chain (always available).** Seal pending v3 events on *your* demo database
(guarded; `--confirm-env` must match `PULSEOS_ENVIRONMENT`), then verify:

```bash
python scripts/audit_integrity.py seal --confirm-env local
python scripts/audit_integrity.py verify-batch --all
```

Patient portal → Audit History: entries show "Integrity verified"; **View proof** shows the
Merkle path, root and commitment, then a separate **Public blockchain anchoring** section that
reads "Not configured" until a chain is set up.

**With a local EVM (real transactions, not public).**

```bash
anvil --host 127.0.0.1 --port 8545 &
cd contracts && forge build && forge create src/AuditCommitmentRegistry.sol:AuditCommitmentRegistry \
  --rpc-url http://127.0.0.1:8545 --unlocked --from 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 \
  --broadcast --constructor-args 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
# backend env: PULSEOS_CHAIN_RPC_URL=http://127.0.0.1:8545 PULSEOS_CHAIN_ID=31337
#   PULSEOS_CHAIN_CONTRACT_ADDRESS=<deployed address> PULSEOS_CHAIN_MIN_CONFIRMATIONS=1
#   PULSEOS_CHAIN_ANCHORER_PRIVATE_KEY=<anvil account 0 key, for the CLI only>
python scripts/audit_integrity.py anchor --batch-number 1 --confirm-env local
python scripts/audit_integrity.py anchor-refresh --batch-number 1 --confirm-env local
python scripts/audit_integrity.py verify-chain --batch-number 1
```

The proof dialog then shows "Local development chain", the transaction hash, block, and
**Verified on-chain** (re-read from the contract on each open). No explorer link exists for a
local chain. Tamper demo: edit one audit row in the *demo* database → the entry reads
"Integrity check failed" and the chain section "Local check failed".

**Public testnet (Polygon Amoy)** — follow `contracts/README.md`; requires an RPC endpoint, a
funded testnet-only key (ADR-035 is accepted for local implementation; public deployment is pending). Not done as of 2026-10-26: do not show or
claim a public transaction until one exists and `verify-chain` reports VERIFIED against it.
