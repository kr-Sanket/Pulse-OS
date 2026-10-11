# CONTEXT.md — Domain Context & Glossary

## The Problem in One Story

A patient treated at TMH Jamshedpur moves to Vellore. At CMC, the doctor asks for reports; the
patient has "some on WhatsApp, some lost." Tests get repeated, money is wasted, diagnosis is
delayed. With PulseOS: the doctor searches the patient's Pulse Health ID, requests specific record
categories, the patient approves in one tap, the doctor gets an AI-generated one-page summary,
and every access is permanently logged where the patient can see it.

## Personas

| Persona | Client | What they do |
|---|---|---|
| **Patient** | Patient web portal (Flutter app not started) | Owns records; uploads to medical locker; approves/rejects/revokes consent; reads audit log; uses the AI Health Copilot (explainer/timeline planned) |
| **Doctor** | Doctor web portal | Searches by Health ID; requests category-scoped access; uses the AI clinical assistant over granted records (summary/timeline planned); downloads approved records; uploads prescriptions |
| **Hospital Admin** | Hospital web portal | Registers hospital (gets `HID-XXXX`); manages doctors; uploads records against Health IDs; handles incoming requests |

## The Three Core Journeys (demo-critical targets — status in ROADMAP.md)

1. **Identity:** register patient → issue `PHI-IND-2026-XXXXXXC` (ADR-012) → QR identity
   (*QR not built*).
2. **Interoperability + Consent (the thesis):** Hospital A uploads records → doctor at Hospital B
   searches ID → sees records *exist* but are locked → requests categories (CBC, MRI,
   Prescriptions) → patient sees the request (*push notification not built*) → approves per
   category → every decision and access is audited and later sealed into a tamper-evident batch
   (*public-chain publication not built*, ADR-027) → doctor reads only approved categories →
   access logged, visible to patient → patient can revoke anytime.
3. **Intelligence:** granted records → consent-scoped retrieval → AI answers with citations for
   the doctor, and the Health Copilot for the patient (local Ollama, ADR-028/029). *OCR, one-page
   summary, timeline and explainer are planned, not built.*

## Glossary

| Term | Meaning |
|---|---|
| **PHI / Pulse Health ID** | Permanent patient identifier, format `PHI-IND-YYYY-XXXXXXC` (random Crockford Base32 + check character, ADR-012). Note: also collides with "Protected Health Information" — in this repo, write **Health ID** for the identifier and **PHI** only for protected health information. |
| **HID** | Hospital ID, format `HID-XXXX` |
| **Record category** | Consent granularity unit: e.g. CBC, MRI, X-Ray, Prescription, Discharge Summary |
| **Consent grant** | Patient approval for one (requester, patient, category-set) tuple, revocable |
| **Audit anchor** | Integrity evidence for audit events: historical per-event anchors (v1/v2) and, for v3 events, Merkle batches whose 32-byte commitment is designed to be published to Polygon Amoy (ADR-027). Nothing is published on-chain yet |
| **Medical locker** | Patient's encrypted file store (S3) |
| **Simulated hospitals** | TMH Jamshedpur (HID-0001), CMC Vellore (HID-0002), Apollo (HID-0003) — seed data, not real integrations |

## Constraints That Shape Every Decision

- **Team:** 3 students (frontend / backend / AI+blockchain leads), heavily AI-assisted coding.
- **Budget:** student-tier. Free and local options preferred (local Ollama, Polygon Amoy testnet,
  Render/MinIO).
- **Timeline:** 7 months, hard demo date. Phase gates in ROADMAP.md are strict.
- **Data:** synthetic only. Never real patient data. This still must be *engineered* as if real
  (the research claim depends on the security design being credible).
- **Ops maturity:** near zero — this is why we run a modular monolith, one database, one deploy
  unit (ADR-001).

## Research Contributions (why this is publishable)

- **RC-1:** Patient-controlled *granular* consent in HIE (vs hospital-to-hospital consent).
- **RC-2:** Blockchain tamper-evident audit trail vs traditional DB logging (with experiments).
- **RC-3:** RAG-based multi-hospital record summarization (evaluated with NLP metrics).
- **RC-4:** Universal Health ID interoperability prototype (3-hospital simulation study).
- Extra credibility lever added in review: **FHIR-aligned data model** (ADR-006) lets the paper
  claim standards-compatibility, which reviewers in health informatics expect.
