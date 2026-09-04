// Backend audit entries → what the Audit History page renders.
//
// All of the page's logic lives here: the action vocabulary, who the actor was, which
// category an event touched, how its timestamps read, and the summary figures. Pure
// functions, no React, so every rule below is unit-testable.
//
// Two rules shape the mapping. **Nothing is invented**: an audit entry carries no purpose
// and no free text, so what is shown is the action, the actor, the category and the time —
// and the digest that makes the row tamper-evident. **Nothing is assumed**: the action
// vocabulary can grow server-side without a frontend release, so an unrecognised action
// degrades to its own humanised name rather than breaking the timeline.
//
// A third rule governs the default view. The page exists to answer "who else touched my
// records?", and a patient's own reading of their own records drowns that answer out — it
// is the one kind of entry they already know about. So those rows are hidden by default and
// one toggle brings them back. **The filter is presentation and nothing else**: the request
// is unchanged, every row is still fetched, and nothing is dropped from the log — see
// `filterAuditEntries`.

import { Building2, Clock, Eye, FlaskConical, UserRound, type LucideIcon } from "lucide-react";

import type { Tone } from "@/components/dashboard/StatusBadge";
import { formatInstantDate, formatInstantTime, formatRelativeTime } from "@pulseos/ui";
import { categoryLabel } from "@pulseos/ui";

import type { ActorRole, AuditAction, AuditEvent } from "./api";

/** Shown for an event whose actor this build cannot name — the projection found no staff
 * row, so the role is all the trail knows. */
const ROLE_LABELS: Readonly<Record<ActorRole, string>> = {
  PATIENT: "You",
  DOCTOR: "A clinician",
  HOSPITAL_ADMIN: "Hospital staff",
  SYSTEM_ADMIN: "PulseOS administrator",
};

/** The patient's own actions read as "You" wherever the actor would otherwise be blank. */
export const SELF_ACTOR = ROLE_LABELS.PATIENT;

/** No category is recorded for events that target a request rather than a record. */
export const NO_CATEGORY = "—";

interface ActionPresentation {
  label: string;
  tone: Tone;
}

/** The ten actions the backend defines (AuditAction), and nothing more. */
const ACTIONS: Readonly<Record<AuditAction, ActionPresentation>> = {
  RECORD_VIEWED: { label: "Viewed", tone: "info" },
  RECORD_DOWNLOADED: { label: "Downloaded", tone: "primary" },
  RECORD_UPLOADED: { label: "Uploaded", tone: "neutral" },
  ACCESS_REQUESTED: { label: "Access requested", tone: "warning" },
  CONSENT_APPROVED: { label: "Consent approved", tone: "success" },
  CONSENT_REJECTED: { label: "Consent declined", tone: "destructive" },
  CONSENT_REVOKED: { label: "Access withdrawn", tone: "destructive" },
  SUMMARY_GENERATED: { label: "Summary generated", tone: "neutral" },
  ACCESS_DENIED: { label: "Access denied", tone: "destructive" },
  // A clinician asked which of your records their consent lets them read. One entry per
  // request, never one per record — and it is not a read: opening any of those records
  // still appears separately as "Viewed".
  RECORDS_LISTED: { label: "Records listed", tone: "info" },
};

/** "SOMETHING_NEW" → "Something new". The graceful path for an action added server-side
 * after this build shipped: it is shown as itself, in neutral, rather than crashing a
 * lookup or being silently dropped from the patient's trail. */
export function humanizeAction(action: string): string {
  const words = action.toLowerCase().split("_").filter(Boolean).join(" ");
  return words.length === 0 ? action : words[0]!.toUpperCase() + words.slice(1);
}

export function actionPresentation(action: string): ActionPresentation {
  return ACTIONS[action as AuditAction] ?? { label: humanizeAction(action), tone: "neutral" };
}

export interface AuditEventView {
  id: string;
  /** The organisation behind the event, or "You" for the patient's own actions. */
  origin: string;
  /** The person, when the trail can name one. Null when the origin already says it all. */
  actor: string | null;
  actionLabel: string;
  actionTone: Tone;
  /** Display name of the category the event touched, or NO_CATEGORY. */
  category: string;
  /** True when a real category was recorded, so the card can render a badge or plain text. */
  hasCategory: boolean;
  date: string;
  time: string;
  /** First and last characters of the tamper-evidence digest, for display. */
  hashPreview: string;
  /** The whole digest, for a title attribute — the page shows a preview, not a secret. */
  eventHash: string;
  /** The rail icon: a person for the patient's own actions, an organisation otherwise. */
  icon: LucideIcon;
}

/** Who the event came from, as two lines. A patient's own action is "You" with nothing
 * beneath it; hospital staff are their hospital with their name beneath. */
export function originOf(event: AuditEvent): { origin: string; actor: string | null } {
  if (event.actorRole === "PATIENT") {
    return { origin: SELF_ACTOR, actor: null };
  }
  const actor = event.actor;
  if (actor === null) {
    return { origin: ROLE_LABELS[event.actorRole], actor: null };
  }
  const specialty = actor.specialty?.trim();
  return {
    origin: actor.hospitalName,
    actor:
      specialty === undefined || specialty.length === 0
        ? actor.fullName
        : `${actor.fullName} · ${specialty}`,
  };
}

/** 64 hex characters is unreadable; the ends are enough to compare two rows by eye. */
function previewHash(hash: string): string {
  return hash.length <= 12 ? hash : `${hash.slice(0, 6)}…${hash.slice(-4)}`;
}

export function toEventView(
  event: AuditEvent,
  labels: ReadonlyMap<string, string>,
): AuditEventView {
  const { origin, actor } = originOf(event);
  const presentation = actionPresentation(event.action);
  const code = event.targetCategoryCode;
  return {
    id: event.id,
    origin,
    actor,
    actionLabel: presentation.label,
    actionTone: presentation.tone,
    category: code === null ? NO_CATEGORY : categoryLabel(labels, code),
    hasCategory: code !== null,
    date: formatInstantDate(event.occurredAt),
    time: formatInstantTime(event.occurredAt),
    hashPreview: previewHash(event.eventHash),
    eventHash: event.eventHash,
    icon: event.actorRole === "PATIENT" ? UserRound : Building2,
  };
}

export function toEventViews(
  events: readonly AuditEvent[],
  labels: ReadonlyMap<string, string>,
): readonly AuditEventView[] {
  return events.map((event) => toEventView(event, labels));
}

// -- the default view ------------------------------------------------------------------
//
// Hiding is decided per row by one predicate, so what the page shows and what the summary
// counts can never disagree: both are computed from the same filtered list.

/**
 * True when the row is the patient reading their own records.
 *
 * Deliberately narrow. Only a *read* by the *patient themselves* is noise — the patient
 * already knows they opened their own file, and every other row is someone else's action
 * or a change to who may act. A hospital's upload, a clinician's view or download, a
 * consent decision, a refusal, and a clinician listing what a grant covers are all kept,
 * including the patient's own consent decisions: approving access is not the same kind of
 * event as reading a page, and it is exactly what this trail exists to evidence.
 */
export function isOwnRecordAccess(event: AuditEvent): boolean {
  return (
    event.actorRole === "PATIENT" &&
    (event.action === "RECORD_VIEWED" || event.action === "RECORD_DOWNLOADED")
  );
}

/**
 * The rows the timeline shows, in the order the API returned them (newest first).
 *
 * A presentation filter over an already-fetched page: nothing is requested differently,
 * nothing is deleted, and turning the toggle on returns the page byte-for-byte as the API
 * sent it. `Array.filter` preserves order, so the trail's chronology survives untouched —
 * which matters, because a reordered audit log would be a different document.
 */
export function filterAuditEntries(
  events: readonly AuditEvent[],
  showOwnActivity: boolean,
): readonly AuditEvent[] {
  return showOwnActivity ? events : events.filter((event) => !isOwnRecordAccess(event));
}

/** How many rows the default view is holding back — what the toggle offers to reveal, and
 * the difference between "nothing has happened" and "nothing has happened *to you*". */
export function countOwnRecordAccess(events: readonly AuditEvent[]): number {
  return events.filter(isOwnRecordAccess).length;
}

/** Copy for the state where the filter leaves the timeline empty. */
export const NO_EXTERNAL_ACCESS = {
  title: "No external access yet",
  body: "No doctors, hospitals or other users have accessed your records yet.",
  action: "Show my activity",
} as const;

export interface SummaryStat {
  id: string;
  label: string;
  value: string;
  unit?: string;
  note: string;
  tone: Tone;
  icon: LucideIcon;
}

export interface SummaryOptions {
  /** Whether the caller is describing the full trail or the default, others-only view. */
  showOwnActivity?: boolean;
  now?: number;
}

/**
 * The four figures above the trail, computed over the events **currently visible** and
 * nothing else.
 *
 * Two limits are stated rather than papered over. The API exposes no aggregate endpoint, so
 * a lifetime total is not available — quietly presenting a page total as one would
 * misrepresent a compliance record. And when the default filter is on these figures describe
 * other people's activity, not everything that happened, so the first note says so. A
 * summary that counted rows the timeline beneath it does not show would be worse than no
 * summary at all.
 */
export function summarizeAuditEntries(
  events: readonly AuditEvent[],
  views: readonly AuditEventView[],
  options: SummaryOptions = {},
): readonly SummaryStat[] {
  const { showOwnActivity = true, now = Date.now() } = options;
  const origins = new Set(
    views.filter((view) => view.origin !== SELF_ACTOR).map((view) => view.origin),
  );
  const busiest = busiestCategory(views);
  const latest = events[0];

  return [
    {
      id: "loaded",
      label: "Events shown",
      value: `${events.length}`,
      note: showOwnActivity ? "On this page only" : "Excluding your own reads",
      tone: "info",
      icon: Eye,
    },
    {
      id: "organisations",
      label: "Organisations involved",
      value: `${origins.size}`,
      note: origins.size === 0 ? "In the events shown" : [...origins].slice(0, 3).join(", "),
      tone: "neutral",
      icon: Building2,
    },
    {
      id: "busiest",
      label: "Most touched record type",
      value: busiest === null ? "—" : `${busiest.count}`,
      unit: busiest === null ? undefined : busiest.count === 1 ? "event" : "events",
      note: busiest?.category ?? "No category recorded",
      tone: "primary",
      icon: FlaskConical,
    },
    {
      id: "latest",
      label: "Most recent event",
      value: latest === undefined ? "—" : formatRelativeTime(latest.occurredAt, now),
      note: views[0]?.actionLabel ?? "Nothing recorded yet",
      tone: "success",
      icon: Clock,
    },
  ];
}

function busiestCategory(
  views: readonly AuditEventView[],
): { category: string; count: number } | null {
  const counts = new Map<string, number>();
  for (const view of views) {
    if (view.hasCategory) {
      counts.set(view.category, (counts.get(view.category) ?? 0) + 1);
    }
  }
  let busiest: { category: string; count: number } | null = null;
  for (const [category, count] of counts) {
    if (busiest === null || count > busiest.count) {
      busiest = { category, count };
    }
  }
  return busiest;
}

/** Copy for the standing privacy card. */
export const AUDIT_PRIVACY = {
  title: "Privacy Information",
  body:
    "Every access to your medical records is permanently logged to provide complete " +
    "transparency.",
  points: [
    "Entries are append-only — they can never be edited or deleted, by anyone.",
    "You see the same trail your providers do, including refused attempts.",
    "Revoking a grant in Active Grants stops further access immediately.",
  ],
} as const;
