# AI Architecture

> Design for the `ai` module + worker pipeline. Provider abstraction and redaction: ADR-007.
> Vector store: pgvector (ADR-002). All processing is asynchronous (ADR-008).

## Ingestion Pipeline (per uploaded record)

```
upload (records module) ──enqueue──▶ WORKER:
  1. fetch file from S3
  2. OCR            EasyOCR (Tesseract fallback) → raw text; skip for born-digital PDFs w/ text layer
  3. clean/segment  strip boilerplate, detect report type, extract key values + dates
  4. chunk          semantic chunks w/ metadata (record id, category, hospital, date)
  5. embed          LLMProvider.embed() → pgvector rows
  6. status         DocumentReference.processingStatus = indexed | failed (+ reason)
```

Failures are visible (status + reason in UI), retried with backoff, and never lose the original
file — OCR quality issues must degrade to "file stored, not searchable," not data loss.

## Retrieval (consent-scoped RAG — the security-critical part)

Retrieval is **one SQL query** combining vector similarity with a consent predicate:
*chunks belonging to records of patient P that requester R currently holds an active grant for*
(patient querying their own records: scope = all their records). There is no code path that
searches "all vectors then filters" — scoping happens in the query. This design is a research
detail (consent-scoped retrieval) and a hard security rule.

## Features Built on the Pipeline

| Feature | Consumer | Mechanism | Notes |
|---|---|---|---|
| **AI Patient Summary** | Doctor | Retrieve granted records → structured prompt → 1-page summary (Conditions, Medications, Allergies, Recent Labs, Surgeries) | Cached per (patient, grant-scope, records-version); invalidated on new indexed record; regenerating is explicit |
| **Medical Timeline** | Patient + Doctor | Extracted (date, event, category) tuples from step 3, LLM-normalized | Stored, incrementally updated — not regenerated per view |
| **Report Explainer** | Patient | Single report's extracted values → plain-English per-value explanation | Hard rule in prompt + UI: understanding, **never diagnosis or medical advice**; fixed disclaimer |
| **Health Copilot (chat)** | Patient | RAG over own records; conversational | Answers cite source records ("from your CBC report, 12 Mar 2025"); refuses medical advice; conversation history stored per patient |
| **Voice assistant** | Patient (Phase 2) | STT → copilot → TTS | Backend reuses copilot; not MVP |

## LLM Provider Layer (ADR-007)

- Single `AnswerGenerator` interface: `generate_answer()`; implementations: Ollama (sole generation provider via local Qwen3:8B),
  fake (tests/local). Model names, temperature, and prompts are versioned code, not scattered strings.
- **Redaction before every external call:** direct identifiers (name, phone, Health ID, address,
  emergency contacts) are stripped/tokenized from prompt content; the LLM works over clinical
  content only. Redaction has its own unit tests and is part of the security review checklist.
- Rate limiting + retry with backoff around provider calls; per-user quotas on copilot to protect
  the free tier. All prompts/responses logged **redacted** for debugging and evaluation.

## Cost & Latency Posture

Summaries and timelines are cached/materialized — LLM calls happen on ingestion and on
cache-miss, not per page view. Copilot is the only interactive LLM surface. Target: warm summary
<1s (cache), cold <15s; copilot first token <5s.

## Evaluation Plan (feeds RC-3 of the paper)

- Build a synthetic patient corpus (generator script, M5) with known ground truth.
- Summary quality: fact-recall/precision against ground truth + ROUGE/BERTScore; hallucination
  count per summary as a headline metric.
- Copilot: question set with known answers; report exact-answer accuracy + citation correctness.
- Compare RAG vs stuff-everything-in-context baseline for the paper's ablation.
