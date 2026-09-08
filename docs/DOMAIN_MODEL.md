# Domain Model

> M0.2 deliverable. Conceptual domain design — the contract for all future implementation.
> FHIR alignment per ADR-006; Health ID per ADR-012; RBAC per ADR-013. No physical schema here
> (that arrives with Alembic migrations, reviewed against this document).

## 1. Entities

### User (identity principal)
The authenticated identity. Holds the auth-provider subject (e.g. Firebase UID), verified
phone/email, exactly one **role** (`PATIENT | DOCTOR | HOSPITAL_ADMIN | SYSTEM_ADMIN`), and
account status (`ACTIVE | SUSPENDED`). A User is linked 1:1 to exactly one profile entity
matching its role (Patient, Doctor, or Hospital-admin membership). System admins have no
domain profile. Users never own medical data directly — profiles do.

### Patient (FHIR: Patient)
The data owner. Internal UUID primary identity; **Health ID** (`PHI-IND-…`, ADR-012) as the
human/business identifier; an **identifiers list** (FHIR-style `system` + `value` pairs) so
external IDs — ABHA later — attach without remodeling. Carries the health profile (blood group,
allergies, chronic conditions, current medications, emergency contacts) and QR payload.
Owns records, consent decisions, and their audit trail.

### Hospital (FHIR: Organization)
A care organization. `HID-XXXX` business ID, name, address, verification status
(`PENDING | VERIFIED`, set by System Admin). Employs Doctors, uploads records, receives and
originates access requests. The three simulated hospitals are ordinary rows, not special cases.

### Doctor (FHIR: Practitioner)
A clinician. 1:1 with a User; affiliated to exactly **one** Hospital in MVP (multi-affiliation
is future scope), with specialty and registration/credential fields. Requests access, reads
granted records, uploads prescriptions.

### MedicalRecord (FHIR: DocumentReference)
Metadata for one clinical document. Belongs to exactly one Patient. Has: **category** (from the
controlled `RecordCategory` vocabulary), origin (`HOSPITAL_UPLOAD` with uploading Hospital +
Doctor, or `PATIENT_LOCKER` for self-uploads), date of service, S3 object key (file itself never
in DB, ADR-005), processing status (`UPLOADED → PROCESSING → INDEXED | FAILED`, ADR-008), and
patient-controlled visibility (a patient may hide **any record they own**, whatever its origin;
hiding withdraws it from what consent can share, and revokes nothing). Derived artifacts (OCR text
chunks, embeddings, timeline entries) hang off the record and die with it.

### RecordCategory (controlled vocabulary)
The consent granularity unit (FHIR `DocumentReference.type`-style codes):
`CBC · LAB_REPORT · MRI · XRAY · CT_SCAN · ULTRASOUND · PRESCRIPTION · DISCHARGE_SUMMARY ·
VACCINATION · OTHER`. A seedable table, not an enum baked into code — adding a category must
not require a migration of logic.

### AccessRequest
A Doctor's petition to see a Patient's records: requester (Doctor, with Hospital context),
target Patient, **set of requested categories**, free-text purpose, status
(`PENDING | DECIDED | EXPIRED | CANCELLED`). Requests expire if undecided (design default:
7 days). One request produces one ConsentDecision per category.

### Consent (FHIR: Consent) — decision + grant
Two concepts, deliberately separate:
- **ConsentDecision** — the immutable historical fact: for (AccessRequest, category), the
  patient decided `APPROVED | REJECTED` at time T. Never updated; revocation is a new event.
- **ConsentGrant** — the *active* permission derived from an approval:
  (patient, grantee doctor, category, granted_at, expires_at, revoked_at). Enforcement reads
  grants only — O(1) check, no history walk. Grantee is the **individual doctor**, not the
  hospital (tightest sensible scope; hospital-wide grants are future scope). Grants carry an
  expiry (design default: 90 days, patient-adjustable at approval — open decision OD-2).

### AuditEvent (FHIR: AuditEvent)
Append-only, patient-visible, blockchain-anchored (ADR-004). Fields: actor (User + role),
action, subject Patient, target (record / category / request), timestamp, request context,
canonical-JSON hash, and an optional AnchorReceipt (chain tx) added asynchronously.
Action vocabulary: `RECORD_UPLOADED · ACCESS_REQUESTED · CONSENT_APPROVED · CONSENT_REJECTED ·
CONSENT_REVOKED · RECORD_VIEWED · RECORD_DOWNLOADED · SUMMARY_GENERATED · EMERGENCY_ACCESS
(Phase 2)`, plus two the implementation added with their own ADRs: `ACCESS_DENIED` (ADR-018 — a
refused read must be logged, and no success verb states that) and `RECORDS_LISTED` (ADR-020 — a
clinician listing what a grant covers). Audit events are written in the same transaction as the
action they record.
**At most one** target is set per event: exactly one for every action naming an object, and
**none** for `RECORDS_LISTED`, whose subject is a scope rather than an object — `patient_id`,
never nullable, carries it (ADR-020).

## 2. Relationship Diagram

```
                         User 1─────1 SystemAdmin (no domain profile)
                          │ 1:1 (by role)
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
     Patient           Doctor  N────1   Hospital
        │1                │1  affiliated    │1
        │                 │                 │
        │                 │ creates         │ uploads (via admin/doctor)
        │                 ▼                 ▼
        │  N       AccessRequest      MedicalRecord N───1 RecordCategory
        ├──────◀──  (categories,           │ N                │
        │  target    purpose)              │ owned by         │
        │            │1                    ▼                  │
        │            │ N per category   Patient               │
        │            ▼                                        │
        │      ConsentDecision (immutable APPROVED/REJECTED)  │
        │            │ approval spawns                        │
        │            ▼                                        │
        ├──────◀ ConsentGrant N───────────────────────────────┘
        │        (patient, doctor, category, expiry, revoked_at)
        │            ▲ checked by consent.enforce() on EVERY read
        │
        └──────◀ AuditEvent (append-only; every action above emits one)
                     └─ AnchorReceipt (async, hash-only on Polygon — ADR-004)
```

Cardinal rules encoded here:
1. Records belong to Patients, never to Hospitals — a hospital retains read access only to
   records **it uploaded** (origin), everything else requires a grant.
2. Consent history is immutable; enforcement state (grants) is derived from it.
3. No entity reaches record content except through `consent.enforce()`.
4. Public/business IDs (`PHI-…`, `HID-…`) are display identifiers; all foreign keys use
  internal UUIDs, so external ID systems (ABHA) attach freely.

## 3. RBAC Model (ADR-013)

Three enforcement layers, in order: **role gate** (can this role ever do this?) →
**relationship check** (own profile? own hospital? own upload?) → **consent check**
(active grant for this patient + category). All three live behind FastAPI dependencies;
the consent layer is the single choke point from SYSTEM_ARCHITECTURE.md.

Legend: ✅ always (within role) · ⭕ conditional (condition noted) · ❌ never.

| Capability | Patient | Doctor | Hospital Admin | System Admin |
|---|---|---|---|---|
| Read/update own profile & health profile | ✅ | ✅ (own) | ✅ (own) | ✅ (own) |
| Search patient by Health ID / QR | ❌ | ⭕ existence + name confirmation only | ⭕ same | ❌ |
| See that records exist (category + hospital level) | ✅ own | ⭕ after search | ⭕ after search | ❌ |
| List which records a grant covers | ✅ own | ⭕ grant-scoped, chooser fields only (ADR-020) | ⭕ own hospital's uploads | ❌ |
| Read record content / download | ✅ own | ⭕ active grant for that category | ⭕ only records their hospital uploaded | ❌ |
| Upload record | ✅ own locker | ⭕ prescription, for patient with active grant | ⭕ for verified patient at their hospital | ❌ |
| Hide/unhide record | ✅ own records only (any origin) | ❌ | ❌ | ❌ |
| Create access request | ❌ | ✅ | ⭕ on behalf of their doctors (dual-consent flows) | ❌ |
| Approve / reject / revoke consent | ✅ own, per category | ❌ | ❌ | ❌ |
| View audit log | ✅ all events about them | ⭕ own actions only | ⭕ their hospital's actions only | ⭕ platform events, **never record content** |
| Manage doctors (add/remove/credentials) | ❌ | ❌ | ✅ own hospital | ❌ |
| Register / verify hospitals | ❌ | ❌ | ⭕ register own | ✅ verify |
| Suspend users / support operations | ❌ | ❌ | ❌ | ✅ |
| AI: copilot, explainer, timeline (own data) | ✅ | ❌ | ❌ | ❌ |
| AI: patient summary, timeline (granted data) | ❌ | ⭕ grant-scoped | ❌ | ❌ |
| Send reminders / follow-ups | ❌ | ❌ | ⭕ to their hospital's patients | ❌ |

**Hiding is scoped to what consent governs, and no further.** A hidden record disappears from
every grantee surface — the existence projection, the grant-scoped listing, the single-record
read and the download — but the row, the file and the grant are all untouched, and the uploading
hospital keeps its layer-2 access to its own upload. A patient-facing screen offering the control
has to say so rather than imply that hiding conceals a record from everyone.

Two deliberate properties worth stating: **System Admin has zero access to medical content**
(platform operations never require PHI; there is no break-glass for admins), and **AI features
are strictly a projection of the same consent scope** — the copilot/summary can never retrieve
what the caller couldn't read directly.

## 4. Universal Health ID (ADR-012)

**Format:** `PHI-IND-YYYY-XXXXXXC`
- `PHI-IND` — namespace (PulseOS Health Identifier, India).
- `YYYY` — issuance year (cohort readability; carries no security meaning).
- `XXXXXX` — 6 characters, **cryptographically random**, Crockford Base32 alphabet
  (no `I L O U` — unambiguous to read aloud, type, and print). Space: 32⁶ ≈ 1.07 billion/year.
- `C` — check character, ISO 7064 (mod 37-2) over the full ID: catches typos and
  transpositions offline, before any API call.

Example: `PHI-IND-2026-7K3M99X` (a genuinely valid ID — the `X` is the computed check
character for body `7K3M99`, year 2026).

**Generation:** draw random candidate → compute check char → INSERT with a DB unique
constraint → on collision (p < 0.1% even at millions of IDs) redraw. No sequences, no
coordination, no lock. IDs are **never reissued** and survive account deletion (tombstoned).

**Why random, not sequential** (the master plan's examples showed `000001`): sequential IDs are
enumerable — an attacker could walk the ID space probing which patients exist, and volume is
disclosed to competitors/reviewers. Random draws from 1.07B kill enumeration at negligible cost.
The display format stays exactly as demo-friendly.

**QR integration:** the identity QR encodes a versioned URI — `pulseos://p/v1/PHI-IND-2026-7K3M99X`
— containing **only** the Health ID (which the check char makes offline-validatable). No name,
no PHI, no signature needed: the QR is a pointer, the server is the authority, and scanning is
useful only to an authenticated Doctor/Hospital Admin whose search permission is rate-limited
and audited. The Phase-2 **emergency QR is a different object** (rotating signed token, own ADR
before build — see SECURITY.md §Break-glass).

**ABHA future-compatibility:** ABHA is a 14-digit identifier in the FHIR-based ABDM stack. Our
Patient carries a FHIR-style identifier list (`system` → `value`); `PHI-IND` is one system,
ABHA becomes a second entry when integration ever happens. Because all internal references use
UUIDs (rule 4 above), linking ABHA is additive — zero remodeling, which is exactly the claim
RC-4 makes in the paper.

## 5. Open Decisions (need PO/architect input, tracked in TODO.md)

- **OD-1** Can hospitals register a patient who hasn't installed PulseOS ("unclaimed" Patient
  pre-created at first visit, claimed later via OTP)? MVP recommendation: **no** — patient must
  self-register first; hospitals verify via QR. Revisit after M3.
- **OD-2** Default consent-grant expiry: 90 days patient-adjustable (recommended) vs non-expiring
  until revoked (matches master plan's wording).
- **OD-3** Does an active grant for *any* category also expose the health profile (allergies,
  medications) to the doctor? Clinically important; recommendation: **yes**, and the summary
  includes it — but it must be an explicit line in the consent screen.
