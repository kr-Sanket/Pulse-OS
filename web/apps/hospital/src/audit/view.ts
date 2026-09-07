// Backend audit rows → what the Audit History page renders. Pure functions, no React.
//
// Everything the page says is decided here: what an action is called, what colour it
// carries, who to name as the actor, and whether a record reference is worth showing. The
// components stay dumb and every rule is unit-tested.
//
// **This module maps; it never infers.** The endpoint withholds the patient, the hospital,
// the digest and every clinical fact, and nothing here reconstructs them from what is left.
// A record id is an identifier, not a description, and it is rendered as one.

import { formatInstantDate, formatInstantTime } from "@pulseos/ui";

import type { Tone } from "@/components/shell/StatusBadge";

import type { ActorRole, AuditAction, HospitalAuditEvent, HospitalAuditPage } from "./api";

interface ActionPresentation {
  label: string;
  tone: Tone;
}

/** The four actions a hospital's own activity can consist of (ADR-022).
 *
 * The other members of the vocabulary — consent decisions, revocations, access requests,
 * listings — are either patient actions, which carry no hospital and never reach this
 * listing, or a clinician's, which do. They are mapped too rather than left to the
 * fallback, because a doctor's request *is* their hospital's activity.
 */
const ACTIONS: Readonly<Record<AuditAction, ActionPresentation>> = {
  RECORD_UPLOADED: { label: "Record uploaded", tone: "neutral" },
  RECORD_VIEWED: { label: "Record viewed", tone: "info" },
  RECORD_DOWNLOADED: { label: "Record downloaded", tone: "primary" },
  ACCESS_DENIED: { label: "Access denied", tone: "destructive" },
  ACCESS_REQUESTED: { label: "Access requested", tone: "warning" },
  RECORDS_LISTED: { label: "Records listed", tone: "info" },
  CONSENT_APPROVED: { label: "Consent approved", tone: "success" },
  CONSENT_REJECTED: { label: "Consent declined", tone: "destructive" },
  CONSENT_REVOKED: { label: "Access withdrawn", tone: "destructive" },
  SUMMARY_GENERATED: { label: "Summary generated", tone: "neutral" },
};

/** Shown for an action this build has never heard of — one added server-side after it
 * shipped. Neutral wording rather than the raw code: an unrecognised identifier in a
 * timeline reads as a fault, and guessing at its meaning would be worse than admitting
 * none. The row is still shown, because dropping an audit entry is not an option. */
export const UNKNOWN_ACTION_LABEL = "Audit event";

export function actionLabel(action: string): string {
  return ACTIONS[action as AuditAction]?.label ?? UNKNOWN_ACTION_LABEL;
}

export function actionTone(action: string): Tone {
  return ACTIONS[action as AuditAction]?.tone ?? "neutral";
}

const ROLE_LABELS: Readonly<Record<ActorRole, string>> = {
  HOSPITAL_ADMIN: "Hospital administrator",
  DOCTOR: "Doctor",
  PATIENT: "Patient",
  SYSTEM_ADMIN: "PulseOS administrator",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role as ActorRole] ?? "Unknown role";
}

/** Shown when the staff projection resolved no name for the actor. The role is what the
 * trail still knows for certain, and it is a truthful answer to "who did this". */
export function actorName(event: HospitalAuditEvent): string {
  const name = event.actor?.fullName?.trim();
  return name === undefined || name.length === 0 ? roleLabel(event.actorRole) : name;
}

/** True when the projection named the actor, so the role can be shown as a secondary
 * detail rather than standing in for a name. */
export function hasNamedActor(event: HospitalAuditEvent): boolean {
  const name = event.actor?.fullName?.trim();
  return name !== undefined && name.length > 0;
}

/** A compact handle for the record an event concerned, or null when it concerned none.
 *
 * The id is the only thing about the record this endpoint returns, so the reference is the
 * id — shortened for reading, never decorated. Fetching the record to show a filename or a
 * category would disclose exactly what the response allow-list withholds, and would append
 * a `RECORD_VIEWED` to the patient's trail for every row rendered here.
 *
 * Null rather than a placeholder: an event with no record target has nothing to say in that
 * position, and "—" would imply a missing value rather than an inapplicable one.
 */
export function recordReference(targetRecordId: string | null): string | null {
  if (targetRecordId === null || targetRecordId.length === 0) {
    return null;
  }
  return targetRecordId.slice(0, 8);
}

export interface AuditEventView {
  id: string;
  actionLabel: string;
  actionTone: Tone;
  /** The actor's name where one is known, otherwise their role — never a user id. */
  actor: string;
  /** The role, shown beside a known name; null when the name *is* the role. */
  role: string | null;
  /** "4 Sep 2026". */
  date: string;
  /** "09:30". */
  time: string;
  /** Short record handle, or null when the event targeted no record. */
  record: string | null;
}

export function toAuditEventView(event: HospitalAuditEvent): AuditEventView {
  const named = hasNamedActor(event);
  return {
    id: event.id,
    actionLabel: actionLabel(event.action),
    actionTone: actionTone(event.action),
    actor: actorName(event),
    role: named ? roleLabel(event.actorRole) : null,
    date: formatInstantDate(event.occurredAt),
    time: formatInstantTime(event.occurredAt),
    record: recordReference(event.targetRecordId),
  };
}

/** The page's rows, in the order the API returned them.
 *
 * Deliberately not re-sorted. The server orders newest-first over the event time the hash
 * covers, and it is the authority — a client-side sort over an accumulating, paginated list
 * could only ever reorder the part that happens to be loaded. */
export function toAuditEventViews(
  events: readonly HospitalAuditEvent[],
): readonly AuditEventView[] {
  return events.map(toAuditEventView);
}

/** Append a freshly loaded page to what is already on screen.
 *
 * De-duplicates on id. Keyset pagination does not repeat rows, so a duplicate would mean a
 * double-fired request — and the cost of being wrong is a React key collision and a row
 * shown twice in a compliance view, which is worth ten lines to make impossible.
 */
export function appendPage(
  loaded: readonly HospitalAuditEvent[],
  page: readonly HospitalAuditEvent[],
): readonly HospitalAuditEvent[] {
  if (loaded.length === 0) {
    return page;
  }
  const seen = new Set(loaded.map((event) => event.id));
  return [...loaded, ...page.filter((event) => !seen.has(event.id))];
}

/** True when the API says another page exists. `nextCursor` is opaque and is only ever
 * echoed back — nothing here builds or parses one. */
export function hasMorePages(page: HospitalAuditPage | null): boolean {
  return page !== null && page.nextCursor !== null;
}

// -- page copy ---------------------------------------------------------------------------
//
// Worded here so the claims this page makes are reviewable in one place. Two of them matter:
// the scope note must not promise a complete security log, and the empty state must not
// claim nothing was accessed.

export const PAGE_DESCRIPTION =
  "Review patient-record access activity performed by staff at your hospital.";

/** What this history does and does not cover. Record listings, Health-ID lookups, doctor
 * activation and hospital registration are **not** in the patient-subject audit log
 * (ADR-022, ADR-023), and a page that let a reader assume otherwise would be worse than one
 * that says nothing. */
export const SCOPE_NOTE =
  "This covers patient-record access captured by PulseOS: uploads, views, downloads and " +
  "refused reads. It is not a complete record of everything your hospital does.";

export const EMPTY_TITLE = "No audit activity yet";

/** Deliberately not "no records accessed": the log knows what it captured, not what
 * happened. */
export const EMPTY_BODY =
  "Patient-record access activity performed by staff at this hospital will appear here.";
