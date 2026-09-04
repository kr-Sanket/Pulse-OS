// Backend access requests → what the clinician's request screens render.
//
// Pure functions, no React: every rule the UI needs — what a status is called, what colour
// it carries, how long ago a request was raised, how long it has left, and what its category
// codes are called — lives here and is unit-tested. Components stay dumb.
//
// One honest limit runs through this file. A request carries a single status, and `DECIDED`
// does not say *how* it was decided: approving some categories and rejecting others is still
// one DECIDED request, and the per-category decisions are not on this response (there is no
// `GET /access-requests/{id}`). So nothing here claims an approval. "Answered" is the most a
// clinician can truthfully be told until that endpoint exists.

import type { Tone } from "@/components/shell/StatusBadge";
import { categoryLabel, formatInstantDate, formatRelativeTime } from "@pulseos/ui";

import {
  MAX_CATEGORIES_PER_REQUEST,
  MAX_PURPOSE_LENGTH,
  type ConsentRequestStatus,
  type SentAccessRequest,
} from "./api";

const MS_PER_DAY = 24 * 60 * 60 * 1000;

const STATUS_LABELS: Readonly<Record<ConsentRequestStatus, string>> = {
  PENDING: "Awaiting patient",
  DECIDED: "Answered",
  EXPIRED: "Expired",
  CANCELLED: "Withdrawn",
};

const STATUS_TONES: Readonly<Record<ConsentRequestStatus, Tone>> = {
  PENDING: "warning",
  DECIDED: "info",
  EXPIRED: "neutral",
  CANCELLED: "neutral",
};

/** What the badge says. `DECIDED` is "Answered", never "Approved" — see the module note. */
export function statusLabel(status: ConsentRequestStatus): string {
  return STATUS_LABELS[status];
}

/** What colour the badge carries. Only a live request is coloured; closed ones are neutral. */
export function statusTone(status: ConsentRequestStatus): Tone {
  return STATUS_TONES[status];
}

/** A request the patient could still answer. */
export function isOpen(status: ConsentRequestStatus): boolean {
  return status === "PENDING";
}

/** "requested 2 hours ago" / "requested yesterday". */
export function requestedAgo(createdAt: string, now: number = Date.now()): string {
  return `requested ${formatRelativeTime(createdAt, now)}`;
}

/**
 * Whole days until a deadline, rounded up: a request lapsing in six hours has one day left,
 * not zero. Negative once the deadline has passed; null if the timestamp is unparseable.
 */
export function daysUntil(iso: string, now: number = Date.now()): number | null {
  const deadline = new Date(iso).getTime();
  return Number.isNaN(deadline) ? null : Math.ceil((deadline - now) / MS_PER_DAY);
}

/**
 * "expires in 6 days" / "expires tomorrow" / "expires today" / "expired".
 *
 * Read from the browser clock while the server decides expiry from its own, so this is a
 * hint, not a ruling: a request may read "expires today" and already be refused as EXPIRED.
 * The API answers 409 in that case, which is what the UI should trust.
 */
export function expiresIn(expiresAt: string, now: number = Date.now()): string {
  const days = daysUntil(expiresAt, now);
  if (days === null) {
    return expiresAt;
  }
  if (days <= 0) {
    return "expired";
  }
  if (days === 1) {
    return "expires tomorrow";
  }
  return `expires in ${days} days`;
}

/** Category display names for the codes a request asked for, in the order it listed them.
 * A code this build has never seen renders as itself — truthful, and never blank. */
export function categoryNames(
  codes: readonly string[],
  labels: ReadonlyMap<string, string>,
): readonly string[] {
  return codes.map((code) => categoryLabel(labels, code));
}

/** Shown when the requester projection resolves to nothing (a deleted staff row). */
export const UNKNOWN_HOSPITAL = "Hospital not identified";

export interface SentRequestView {
  id: string;
  /** Who the request is about — the one fact a clinician cannot recover from context. */
  patientHealthId: string;
  /** The hospital the request was raised under. */
  hospital: string;
  purpose: string;
  /** Display names, for the badges. */
  categories: readonly string[];
  /** The codes themselves, kept for a future "ask again". */
  categoryCodes: readonly string[];
  status: ConsentRequestStatus;
  statusLabel: string;
  statusTone: Tone;
  /** "requested 2 hours ago". */
  requestedAgo: string;
  /** "12 Sep 2026". */
  requestedOn: string;
  /** "expires in 6 days" — null once the request is closed, where it means nothing. */
  expiresIn: string | null;
}

export function toSentRequestView(
  request: SentAccessRequest,
  labels: ReadonlyMap<string, string>,
  now: number = Date.now(),
): SentRequestView {
  return {
    id: request.id,
    patientHealthId: request.patientHealthId,
    hospital: request.requesterHospitalName ?? request.requester?.hospitalName ?? UNKNOWN_HOSPITAL,
    purpose: request.purpose,
    categories: categoryNames(request.categoryCodes, labels),
    categoryCodes: request.categoryCodes,
    status: request.status,
    statusLabel: statusLabel(request.status),
    statusTone: statusTone(request.status),
    requestedAgo: requestedAgo(request.createdAt, now),
    requestedOn: formatInstantDate(request.createdAt),
    expiresIn: isOpen(request.status) ? expiresIn(request.expiresAt, now) : null,
  };
}

export function toSentRequestViews(
  requests: readonly SentAccessRequest[],
  labels: ReadonlyMap<string, string>,
  now: number = Date.now(),
): readonly SentRequestView[] {
  return requests.map((request) => toSentRequestView(request, labels, now));
}

// -- drafting a request --------------------------------------------------------------------
//
// Pure rules, so the dialog can stay dumb and the hook can stay short. Each mirrors a
// constraint the API already enforces (the constants come from api.ts, never restated here):
// catching them locally saves a round trip, and the server remains the authority.

export const PURPOSE_REQUIRED = "Say why you need access — the patient sees this.";
export const PURPOSE_TOO_LONG = `Keep the purpose under ${MAX_PURPOSE_LENGTH} characters.`;
export const NO_CATEGORIES_SELECTED = "Select at least one kind of record.";
export const TOO_MANY_CATEGORIES = `Select at most ${MAX_CATEGORIES_PER_REQUEST} kinds of record.`;

/** Why this purpose cannot be sent, or null when it can. */
export function purposeProblem(purpose: string): string | null {
  const trimmed = purpose.trim();
  if (trimmed.length === 0) {
    return PURPOSE_REQUIRED;
  }
  if (trimmed.length > MAX_PURPOSE_LENGTH) {
    return PURPOSE_TOO_LONG;
  }
  return null;
}

/** Why this selection cannot be sent, or null when it can. */
export function selectionProblem(categoryCodes: readonly string[]): string | null {
  if (categoryCodes.length === 0) {
    return NO_CATEGORIES_SELECTED;
  }
  if (categoryCodes.length > MAX_CATEGORIES_PER_REQUEST) {
    return TOO_MANY_CATEGORIES;
  }
  return null;
}

/** The first thing wrong with a draft, in the order a reader would notice it. */
export function draftProblem(categoryCodes: readonly string[], purpose: string): string | null {
  return selectionProblem(categoryCodes) ?? purposeProblem(purpose);
}

/** Characters left before the API would refuse the purpose — for the counter under the field. */
export function purposeRemaining(purpose: string): number {
  return MAX_PURPOSE_LENGTH - purpose.trim().length;
}

// -- grouping the listing --------------------------------------------------------------------
//
// One section per request status, in the order a clinician cares about them: what is still
// waiting on someone, then what is settled. Grouping is strictly by the status the API
// reported — nothing here re-derives a status from a date, because the server is the
// authority on whether a request can still be answered.

export type RequestBucket = "pending" | "answered" | "expired" | "withdrawn";

export interface RequestBuckets {
  pending: readonly SentRequestView[];
  answered: readonly SentRequestView[];
  expired: readonly SentRequestView[];
  withdrawn: readonly SentRequestView[];
}

export const NO_REQUESTS: RequestBuckets = {
  pending: [],
  answered: [],
  expired: [],
  withdrawn: [],
};

/** Section order, and the status each one holds. Headings and tones come from
 * `statusLabel`/`statusTone`, so a section can never disagree with the badges inside it. */
export const REQUEST_SECTIONS: readonly { bucket: RequestBucket; status: ConsentRequestStatus }[] =
  [
    { bucket: "pending", status: "PENDING" },
    { bucket: "answered", status: "DECIDED" },
    { bucket: "expired", status: "EXPIRED" },
    { bucket: "withdrawn", status: "CANCELLED" },
  ];

const BUCKETS: Readonly<Record<ConsentRequestStatus, RequestBucket>> = {
  PENDING: "pending",
  DECIDED: "answered",
  EXPIRED: "expired",
  CANCELLED: "withdrawn",
};

export function bucketOf(status: ConsentRequestStatus): RequestBucket {
  return BUCKETS[status];
}

/** Every request filed under its section, preserving the API's newest-first order. */
export function groupSentRequests(views: readonly SentRequestView[]): RequestBuckets {
  const grouped: Record<RequestBucket, SentRequestView[]> = {
    pending: [],
    answered: [],
    expired: [],
    withdrawn: [],
  };
  for (const view of views) {
    grouped[bucketOf(view.status)].push(view);
  }
  return grouped;
}
