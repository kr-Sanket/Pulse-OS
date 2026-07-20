# PulseOS — Project Overview

**One Patient. One Identity. One Health History. Accessible Anywhere.**

Final-year project (2026, team of 3) building a patient-centric healthcare interoperability
platform for India, with production-grade engineering standards and a research publication goal.
Source master plan: `PulseOS_Project_Plan.docx` (root). This doc is its maintained distillation;
where they conflict, the `.claude/DECISIONS.md` ADRs win.

## Problem

Healthcare data in India is fragmented. When a patient changes cities or hospitals, their medical
history effectively disappears: records are scattered across WhatsApp, email, paper, and hospital
silos; hospitals cannot share records; tests are repeated at the patient's cost; hospitals — not
patients — control access; and raw records (50 PDFs) are unintelligible to patients and
time-costly for doctors.

## Solution

1. **Universal Health Identity** — permanent `PHI-IND-2026-XXXXXX` per patient, plus QR identity.
2. **Patient-controlled granular consent** — doctors request record *categories*; the patient
   approves/rejects each individually and can revoke anytime; every access is logged and visible
   to the patient forever.
3. **Tamper-evident audit** — consent and access events anchored (hash-only) to Polygon Amoy.
4. **AI intelligence layer** — OCR + consent-scoped RAG powering: one-page doctor summaries,
   auto-generated health timeline, plain-English report explainer, Health Copilot chat.
5. **Simulated ecosystem** — 3 hospitals (TMH Jamshedpur HID-0001, CMC Vellore HID-0002,
   Apollo HID-0003) with synthetic data; no real integrations.

## Feature Inventory by Portal

**Patient (Flutter app + web):** Health ID, QR identity, health profile (blood group, allergies,
conditions, medications, emergency contacts), medical locker (encrypted uploads), AI timeline,
AI report explainer, AI Health Copilot chat, consent management (approve/reject/revoke), access
audit log. *Phase 2:* voice assistant, medication & appointment reminders, emergency QR, family accounts.

**Doctor (web):** patient search by Health ID/QR, category-scoped access requests, AI patient
summary, timeline view, prior-hospital history, logged report downloads, prescription upload.

**Hospital (web):** registration (HID), doctor management with RBAC, record upload (drag-drop,
bulk) against Health IDs, incoming request management, patient verification via QR/ID,
follow-up & reminder notifications.

## Scope Boundaries

| MVP (must build) | Phase 2 (if time) | Future (never in this project) |
|---|---|---|
| Health ID system | Voice assistant | ABHA integration |
| QR identity card | Medication reminders | Lab direct upload |
| Medical locker | Appointment reminders | Pharmacy integration |
| Consent request flow | Emergency QR mode | Insurance claims |
| Blockchain audit anchor | Family accounts | Telemedicine |
| AI patient summary | | Predictive health alerts |
| AI timeline | | Analytics dashboard |
| AI Health Copilot | | Regional languages |
| Doctor portal | | |
| Hospital portal (3 simulated) | | |

## Research Contributions & Publication

- **RC-1** Patient-controlled granular consent in Health Information Exchange (primary novelty).
- **RC-2** Blockchain tamper-evident audit trail vs traditional DB logging (experiment: the
  reconciliation job detecting a tampered row — see BLOCKCHAIN_ARCHITECTURE.md).
- **RC-3** Consent-scoped RAG summarization of multi-hospital records (evaluated with NLP metrics
  — see AI_ARCHITECTURE.md §Evaluation).
- **RC-4** Universal Health ID interoperability prototype, FHIR-aligned (ADR-006).

Target venues: IEEE/ACM health-informatics & digital-health conferences; Springer healthcare
technology journals; IRJET/IJERT nationally.

## Team

| Role | Owns |
|---|---|
| Member 1 — Frontend Lead | React monorepo (3 portals), Flutter app, Figma, QR, notifications UI |
| Member 2 — Backend Lead | FastAPI monolith, PostgreSQL, auth, S3, notifications, Docker, deploy |
| Member 3 — AI + Blockchain Lead | OCR pipeline, RAG (pgvector), summaries/timeline/copilot, Solidity contract, anchoring |
| ChatGPT | Chief Software Architect |
| Claude | Senior Software Engineer |
| Human | Product Owner / Integrator |

Timeline & milestones: `.claude/ROADMAP.md`. Architecture: `docs/SYSTEM_ARCHITECTURE.md`.
