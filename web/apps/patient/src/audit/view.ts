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

import type { ActorRole, AuditAction, AuditEvent, AuditIntegrity, AuditProof } from "./api";

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

/** Shown for a clinician event with no recorded hospital: every event written before
 * attribution existed (migration 0005). Named rather than hidden, and never merged into a
 * real hospital — inferring one would mean the present-affiliation join ADR-023 refuses. */
export const UNATTRIBUTED_ORIGIN = "Unattributed activity";

export const UNATTRIBUTED_NOTE =
  "Historical hospital attribution is available for activity recorded since September 2026.";

/** The heading for the patient's own actions. They belong to no organisation. */
export const SELF_ORIGIN = "Your own activity";

interface ActionPresentation {
  label: string;
  tone: Tone;
}

/** The twelve actions the backend defines (AuditAction), and nothing more. */
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
  // A clinician's AI search across the records your consent covers. Unlike a listing it
  // returns record text, so it is named for what it is. One entry per search.
  RECORDS_SEARCHED: { label: "Records searched (AI)", tone: "info" },
  // A FHIR R4 bundle of records was exported — by you, or by a clinician within the
  // categories your consent covers. One entry per export.
  RECORD_EXPORTED: { label: "Records exported (FHIR)", tone: "primary" },
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
  /** The backend's verdict on this row, worded. Never inferred from the hash being present. */
  integrity: IntegrityView;
  /** Accessible name for this row's "View proof" button — every row's visible text is the
   * same, so the name carries which entry it opens. */
  proofButtonLabel: string;
  /** The rail icon: a person for the patient's own actions, an organisation otherwise. */
  icon: LucideIcon;
}

/**
 * Who the event came from, as two lines.
 *
 * **The origin is the hospital recorded on the event, never the actor's current employer**
 * (ADR-025). `actor.hospitalName` is the staff projection's answer to "where does this
 * person work now" — the right question in the consent inbox, the wrong one in a
 * historical log, where it would move a clinician's past activity to a new hospital the
 * day they changed jobs. This page used to read that field; it no longer does.
 *
 * An event with no recorded hospital says so rather than borrowing one.
 */
export function originOf(event: AuditEvent): { origin: string; actor: string | null } {
  if (event.actorRole === "PATIENT") {
    return { origin: SELF_ACTOR, actor: null };
  }
  return { origin: event.actorHospital?.name ?? UNATTRIBUTED_ORIGIN, actor: actorNameOf(event) };
}

/** The person, as the trail can name them. Null when it knows no name — the role label
 * already stands in for the origin in that case. */
export function actorNameOf(event: AuditEvent): string | null {
  const actor = event.actor;
  if (actor === null) {
    return null;
  }
  const specialty = actor.specialty?.trim();
  return specialty === undefined || specialty.length === 0
    ? actor.fullName
    : `${actor.fullName} · ${specialty}`;
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
    integrity: integrityView(event.integrity),
    proofButtonLabel: `View integrity proof: ${presentation.label}, ${formatInstantDate(
      event.occurredAt,
    )} at ${formatInstantTime(event.occurredAt)}`,
    icon: event.actorRole === "PATIENT" ? UserRound : Building2,
  };
}

export function toEventViews(
  events: readonly AuditEvent[],
  labels: ReadonlyMap<string, string>,
): readonly AuditEventView[] {
  return events.map((event) => toEventView(event, labels));
}

// -- integrity --------------------------------------------------------------------------
//
// The verdict comes from the API (`integrity.status`), computed server-side on every read:
// the row's digest is recomputed and, for a sealed event, proven a leaf of its Merkle batch.
// The page words that verdict and nothing more. It never upgrades a row to "verified"
// because it has a hash, and it never calls a local Merkle batch a blockchain anchor —
// PulseOS publishes nothing to any chain today.

/** The batch network the API reports for local Merkle sealing (ADR-027). */
export const LOCAL_MERKLE_BATCH_NETWORK = "local-merkle-batch";

export interface IntegrityView {
  status: AuditIntegrity["status"] | "UNKNOWN";
  label: string;
  tone: Tone;
  /** One sentence on what the verdict does and does not mean. */
  detail: string;
  /** True when the event sits in a local Merkle batch, so a membership proof exists. */
  batched: boolean;
}

const INTEGRITY_UNAVAILABLE: IntegrityView = {
  status: "UNKNOWN",
  label: "Integrity unavailable",
  tone: "neutral",
  detail: "PulseOS did not report an integrity result for this entry.",
  batched: false,
};

export function integrityView(integrity: AuditIntegrity | null | undefined): IntegrityView {
  if (integrity === null || integrity === undefined) {
    return INTEGRITY_UNAVAILABLE;
  }
  const batched = integrity.network === LOCAL_MERKLE_BATCH_NETWORK;
  switch (integrity.status) {
    case "VERIFIED":
      return {
        status: "VERIFIED",
        label: "Integrity verified",
        tone: "success",
        detail: batched
          ? "Unchanged since it was sealed into a local Merkle batch. Not anchored to a public blockchain."
          : "Unchanged since it was anchored by the local development anchor. Not a public blockchain.",
        batched,
      };
    case "NOT_ANCHORED":
      return {
        status: "NOT_ANCHORED",
        label: "Not yet sealed",
        tone: "warning",
        detail:
          "Recorded, but not yet sealed into an integrity batch, so it cannot be verified yet.",
        batched: false,
      };
    case "EVENT_ALTERED":
      return {
        status: "EVENT_ALTERED",
        label: "Integrity check failed",
        tone: "destructive",
        detail: "This entry no longer matches the digest it was sealed with.",
        batched,
      };
    case "ANCHOR_ALTERED":
      return {
        status: "ANCHOR_ALTERED",
        label: "Integrity check failed",
        tone: "destructive",
        detail: "The seal recorded for this entry does not verify.",
        batched,
      };
    default:
      return INTEGRITY_UNAVAILABLE;
  }
}

export interface ProofRow {
  label: string;
  value: string;
  /** Long hex values render monospaced and wrap. */
  mono?: boolean;
}

/** The proof endpoint's answer as label/value rows. Digests are public attestation
 * material — they reveal nothing about the event beyond what this page already shows. */
export function proofRows(proof: AuditProof): readonly ProofRow[] {
  return [
    { label: "Batch", value: `#${proof.batchNumber}` },
    { label: "Position", value: `Leaf ${proof.leafIndex + 1} of ${proof.leafCount}` },
    { label: "Event digest matches", value: proof.isEventValid ? "Yes" : "No" },
    { label: "Inclusion proof valid", value: proof.isProofValid ? "Yes" : "No" },
    { label: "Proof steps", value: `${proof.proofStepsCount}` },
    { label: "Event digest (Keccak-256)", value: proof.eventDigest, mono: true },
    { label: "Batch Merkle root", value: proof.root, mono: true },
    { label: "Batch commitment", value: proof.commitment, mono: true },
  ];
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

// -- grouping --------------------------------------------------------------------------
//
// Origin → actor → events, so a patient can answer "who has been in my records" without
// reading every row. Three rules hold the structure honest:
//
//   * **Grouping happens after filtering, never before.** The own-activity toggle decides
//     which events exist for this render; groups are built from exactly those. A hidden row
//     can therefore never inflate a count or conjure a group that has nothing in it.
//   * **Every visible event lands in exactly one group.** Nothing is merged for tidiness and
//     nothing is dropped; `groupedEventCount` exists so a test can assert that against the
//     input length rather than trusting it.
//   * **Counts describe the events loaded so far**, not the patient's whole history. The API
//     publishes no total, so presenting one would be a fiction — the page says "so far".

/** Which kind of heading an origin group is. Only `hospital` is an organisation. */
export type OriginKind = "hospital" | "self" | "unattributed";

export interface ActorGroup {
  /** `actorUserId` — stable, and already on every row. */
  key: string;
  name: string;
  eventCount: number;
  /** ISO instant of this group's most recent event, for the header. */
  latestAt: string;
  events: readonly AuditEventView[];
}

export interface OriginGroup {
  /** The hospital's `hid`, or the sentinel for the two non-hospital groups. */
  key: string;
  kind: OriginKind;
  title: string;
  eventCount: number;
  latestAt: string;
  actors: readonly ActorGroup[];
}

export const SELF_GROUP_KEY = "self";
export const UNATTRIBUTED_GROUP_KEY = "unattributed";

/** Which group an event belongs to, and why. A patient's own action is theirs before it is
 * anything else — they have no hospital, so no other branch could claim it. */
export function originKeyOf(event: AuditEvent): { key: string; kind: OriginKind; title: string } {
  if (event.actorRole === "PATIENT") {
    return { key: SELF_GROUP_KEY, kind: "self", title: SELF_ORIGIN };
  }
  const hospital = event.actorHospital;
  if (hospital === null) {
    return { key: UNATTRIBUTED_GROUP_KEY, kind: "unattributed", title: UNATTRIBUTED_ORIGIN };
  }
  return { key: hospital.hid, kind: "hospital", title: hospital.name };
}

/**
 * Build the origin → actor → event tree over the events currently visible.
 *
 * The input is already newest-first and insertion order is preserved throughout, so events
 * within an actor stay in the order the API returned them. Groups are then ordered by their
 * own most recent event, which is what makes the first thing on the page the last thing
 * that happened.
 */
export function groupAuditEvents(
  events: readonly AuditEvent[],
  labels: ReadonlyMap<string, string>,
): readonly OriginGroup[] {
  const origins = new Map<
    string,
    { kind: OriginKind; title: string; actors: Map<string, ActorGroup> }
  >();

  for (const event of events) {
    const origin = originKeyOf(event);
    let bucket = origins.get(origin.key);
    if (bucket === undefined) {
      bucket = { kind: origin.kind, title: origin.title, actors: new Map() };
      origins.set(origin.key, bucket);
    }
    const actorKey = event.actorUserId;
    const existing = bucket.actors.get(actorKey);
    const view = toEventView(event, labels);
    if (existing === undefined) {
      bucket.actors.set(actorKey, {
        key: actorKey,
        name: actorLabelOf(event),
        eventCount: 1,
        latestAt: event.occurredAt,
        events: [view],
      });
      continue;
    }
    bucket.actors.set(actorKey, {
      ...existing,
      eventCount: existing.eventCount + 1,
      latestAt: laterOf(existing.latestAt, event.occurredAt),
      events: [...existing.events, view],
    });
  }

  const groups = [...origins.entries()].map(([key, bucket]) => {
    const actors = [...bucket.actors.values()].sort(byLatestDescending);
    return {
      key,
      kind: bucket.kind,
      title: bucket.title,
      eventCount: actors.reduce((total, actor) => total + actor.eventCount, 0),
      latestAt: actors.reduce(
        (latest, actor) => laterOf(latest, actor.latestAt),
        actors[0]?.latestAt ?? "",
      ),
      actors,
    };
  });
  return groups.sort(byLatestDescending);
}

/** How an actor is headed inside a group: their name, or the role the trail recorded when
 * it knows none. Never blank — a nameless heading would read as a rendering fault. */
function actorLabelOf(event: AuditEvent): string {
  if (event.actorRole === "PATIENT") {
    return SELF_ACTOR;
  }
  return actorNameOf(event) ?? ROLE_LABELS[event.actorRole];
}

function laterOf(a: string, b: string): string {
  return b > a ? b : a;
}

function byLatestDescending(a: { latestAt: string }, b: { latestAt: string }): number {
  return a.latestAt < b.latestAt ? 1 : a.latestAt > b.latestAt ? -1 : 0;
}

/** Total events across the tree — the invariant a test compares against the input length. */
export function groupedEventCount(groups: readonly OriginGroup[]): number {
  return groups.reduce((total, group) => total + group.eventCount, 0);
}

/**
 * Which groups start open: the most recent origin, and the most recent actor inside it.
 *
 * Computed once from the first grouping the page sees and then left alone — recomputing as
 * pages load would reopen groups the reader had deliberately closed, and Load more must not
 * rearrange the page under them.
 */
export function initialExpansion(groups: readonly OriginGroup[]): {
  origins: readonly string[];
  actors: readonly string[];
} {
  const first = groups[0];
  if (first === undefined) {
    return { origins: [], actors: [] };
  }
  const actor = first.actors[0];
  return {
    origins: [first.key],
    actors: actor === undefined ? [] : [actorPath(first.key, actor.key)],
  };
}

/** Actor keys are only unique inside their origin — the same clinician can appear under two
 * hospitals once they have worked at both. */
export function actorPath(originKey: string, actorKey: string): string {
  return `${originKey}/${actorKey}`;
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
    "Entries are append-only in PulseOS: the application never edits or deletes them, and " +
      "sealed entries are checked for tampering every time you open this page.",
    "You see the same trail your providers do, including refused attempts.",
    "Revoking a grant in Active Grants refuses every new request at once; a download link " +
      "issued just before stays valid for at most five minutes.",
  ],
} as const;
