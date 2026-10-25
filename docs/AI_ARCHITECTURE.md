# AI Architecture

> **Canonical source for AI behaviour.** Describes the `ai` module **as built** (verified
> against `backend/app/modules/ai/` on 2026-10-11; consent revalidation added 2026-10-25) and, separately, the original plan that is
> **not** implemented. Decisions: ADR-028 (Ollama as the sole generation provider; supersedes
> ADR-007's provider and redaction parts) and ADR-029 (deterministic lexical retrieval; pgvector
> deferred; amends ADR-002). Milestone status: `.claude/ROADMAP.md` §M5.

## What is implemented

### Ingestion — FHIR resources only

```
Synthea import (scripts/import_synthea.py)  ─┐
                                             ├─▶ AIRecordIngestion.index_fhir_resource()
Backfill (scripts/backfill_ai.py)           ─┘      1. normalize   ai/text.py: sanitized FHIR JSON → stable readable text
                                                    2. chunk       ai/chunking.py: deterministic chunks + SHA-256 content hash
                                                    3. persist     ai_documents / ai_chunks (patient, record, category)
```

- **Source data is sanitized FHIR R4 JSON** written by the Synthea import (see
  [DOMAIN_MODEL.md](DOMAIN_MODEL.md) §Synthetic data). Ingestion runs inside the import, or later
  from `scripts/backfill_ai.py` over records already in object storage.
- **Uploaded PDFs with a text layer are indexed; images and scanned PDFs are not** (branch
  `feature/upload-ai-indexing`, proposed ADR-033). `POST /records` enqueues `record_uploaded`;
  the arq worker (`records/upload_indexing.py`) reads the object, extracts text with `pypdf`
  (`records/text_extraction.py`, ≤ 300 pages / 500 000 characters) and writes `ai_documents` /
  `ai_chunks` with the record's patient and category, then sets `processing_status`:
  `INDEXED`; `FAILED` for a PDF with no text layer, an encrypted or unparseable file
  (deterministic — not retried) or storage still failing on the last of 5 attempts; JPEG/PNG
  stay `UPLOADED`. **There is no OCR**, so scanned documents are never searchable. Indexing is
  idempotent (UNIQUE `ai_documents.record_id`; a concurrent duplicate delivery is a no-op,
  validated on PostgreSQL). `scripts/backfill_ai.py --uploads` indexes PDFs stored before the
  worker existed. Extracted text is PHI at rest like imported FHIR text; it is read only
  through the retrieval paths below (consent scope and `is_hidden` evaluated per query) and is
  never logged — `pypdf` and database-driver loggers are pinned to WARNING.
- **No embeddings are computed or stored.** `ai_documents` and `ai_chunks` (migration
  `aedb0169a4eb`) hold text, ordering and content hashes — no vector column.
- Re-indexing is content-hash based: an unchanged resource is not rewritten.

### Retrieval — deterministic lexical scoring, consent-scoped

- `ai/retrieval.py` normalizes the query into terms (lower-cased, punctuation stripped, a naive
  singular form, expanded by a fixed **clinical-synonym** table) and scores each chunk by **how
  many distinct terms occur in its text as substrings** (`lexical_score`). There is no stopword
  list, TF-IDF or BM25. Ranking is deterministic (score, then date of service, with a recency tier
  for "latest/recent" questions). No vector similarity, no LangChain, no external search service.
- **Scope is decided before retrieval, in SQL** (`ai/repository.py`): only chunks with
  `patient_id = P` **and** `category_id IN (allowed categories)`.
  - **Clinician:** allowed categories come from `ConsentService.granted_category_ids` — the same
    grant predicate enforcement uses (active, unrevoked, unexpired grants for that doctor).
  - **Patient (own records):** every category in the vocabulary.
- **Hidden records.** Clinician retrieval (`AIRepository.search_grantee_chunks`) joins chunks to
  `medical_records` and excludes `is_hidden` records **in the query**. They never reach scoring,
  the result limit, generation context or citations. The patient's own retrieval keeps them, as
  every owner surface does. The caller must choose the policy (`RetrievalVisibility.GRANTEE` or
  `OWNER`); there is no default. Visibility is read live and AI rows are untouched, so hiding and
  unhiding take effect without re-indexing. Answers already delivered cannot be recalled.

### Context assembly and generation

- `ai/context.py` assembles an ordered, token-bounded evidence package (audience `CLINICIAN` or
  `PATIENT`) with chunk/record/category references.
- `ai/generation.py` defines the **`AnswerGenerator`** protocol (`generate_answer(context)` →
  answer + citations) and a deterministic fake used by tests.
- **Ollama is the only real provider** (`ai/providers/ollama.py`, ADR-028): local HTTP to
  `PULSEOS_OLLAMA_BASE_URL` (default `http://localhost:11434`), model `PULSEOS_OLLAMA_MODEL`
  (default `qwen3:8b`), timeout `PULSEOS_OLLAMA_TIMEOUT_SECONDS` (default 60), structured JSON
  output with citations. `PULSEOS_AI_PROVIDER` is `ollama` (default) or `fake`. No Gemini or other
  external provider exists in code.
- **Empty evidence** returns a fixed "the available records do not contain…" answer without
  calling the model.
- Provider failures map to HTTP: timeout → 504, unavailable → 503, malformed response → 502.

### Endpoints and UI (from the generated OpenAPI)

| Endpoint | Role | Rate limit | Notes |
|---|---|---|---|
| `GET /api/v1/ai/patients/{patient_id}/search` | DOCTOR | `ai_search` (30 / 60 s) | Returns ranked chunk text within granted categories, hidden records excluded; one audit event per request (see Audit) |
| `POST /api/v1/ai/patients/{patient_id}/answer` | DOCTOR | `ai_generate` (10 / 60 s) | Clinical assistant answer with citations |
| `POST /api/v1/ai/me/answer` | PATIENT | `ai_generate` (10 / 60 s) | Patient Health Copilot over own records |

- UI: doctor portal `AIAssistantPanel`, placed above the granted-records list on the patient
  records page (`13e2034`); patient portal `HealthCopilotPanel` on the records page. No UI calls
  the search endpoint.
- **Citations:** reconciled against the answer text for every generator (`ai/citations.py`):
  `[N]` / `[a, b]` markers naming evidence that was not supplied are removed from the text, and
  only indices that appear as markers in the text are returned as citations, rebuilt from the
  supplied evidence (never from generator-provided record ids). Whether a sentence is actually
  supported by the evidence it cites is not checked — that is semantic, not a string rule.
- **Audit:** a successful generated answer writes a `SUMMARY_GENERATED` audit event for the
  patient. The search writes one scope-level event per request (ADR-020 amendments,
  2026-10-15): `RECORDS_SEARCHED` when the clinician had a granted scope (after retrieval, also
  when nothing matched), `ACCESS_DENIED` when the scope was empty, nothing when the id names no
  patient. The patient and hospital audit views label it "Records searched (AI)". The query and
  chunk text are never stored or logged. Limitations: the query is sent in the URL query string;
  an answer whose granted scope finds no evidence (nothing was accessed), or whose generation
  fails operationally (503/504/502), is not audited.
- **Consent revalidation (`0ea4bac` and follow-up).** Grants can be revoked while a request is in
  flight, so clinician paths check twice:
  - *Search:* grants are re-read after retrieval and chunks from revoked categories are dropped;
    if none remain the request is audited `ACCESS_DENIED` instead of `RECORDS_SEARCHED`.
  - *Doctor answer:* with no live grant the generator is never called, an `ACCESS_DENIED` event is
    written and an empty-evidence answer returned. After generation the grants are re-checked; if
    any evidence category was revoked — or an evidence item cannot be mapped to a category (fail
    closed) — the answer and citations are discarded, `ACCESS_DENIED` is written, and
    `SUMMARY_GENERATED` is not.
  - The patient copilot reads the owner's records and has no grant to revalidate.
- **Query sanitization:** `sanitize_clinical_query` replaces Health IDs and phone numbers in the
  question with placeholders. This is **not** a redaction layer: evidence text sent to the model
  is not redacted (see Privacy below).

### Privacy boundary (as built)

- Generation is **local** (Ollama on the configured host). If `PULSEOS_OLLAMA_BASE_URL` points at
  another machine, clinical evidence travels there — the boundary is the Ollama host, not the API
  process.
- Local inference does not remove privacy risk: prompts carry clinical evidence, model output can
  be wrong, and logs/monitoring on the Ollama host are outside PulseOS's control.
- **No external LLM provider may be added** without first deciding a redaction and data-sharing
  policy (ADR-028).

## Not implemented — original plan (kept for reference, not a commitment)

The design below is from the original plan (ADR-002, ADR-007, ADR-008). None of it exists in
code; nothing here is scheduled unless ROADMAP.md says so.

- OCR of uploaded files (EasyOCR / Tesseract) and a worker pipeline advancing records
  `UPLOADED → PROCESSING → INDEXED | FAILED`.
- Embeddings and vector similarity in pgvector; LangChain orchestration (pgvector deferred,
  ADR-029).
- AI Patient Summary with caching and invalidation; Medical Timeline extraction; Report
  Explainer; stored copilot conversation history; voice assistant (Phase 2).
- A redaction layer before external LLM calls (only relevant if an external provider is ever
  adopted — ADR-028).
- Per-user AI quotas beyond the `ai_generate` rate limit; prompt/response logging.

## Evaluation (research, RC-3)

The original evaluation plan (synthetic corpus with ground truth; fact recall/precision,
hallucination counts, citation correctness; RAG vs full-context baseline) still applies as a
research intent. **No evaluation harness or results exist yet.**
