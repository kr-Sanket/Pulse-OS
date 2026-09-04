// Backend access requests → what the Consent Requests page renders.
//
// All of the page's mapping lives here: which section a request belongs in, what its badge
// says, how its requester reads, and how its timestamps read. Pure functions, no React, so
// every rule below is unit-testable.
//
// **The four-way split is only partly answerable from the inbox.** A request carries one
// status — PENDING, DECIDED, EXPIRED or CANCELLED — and DECIDED does not say *how* it was
// decided: approving some categories and rejecting others is still one DECIDED request, and
// the per-category decisions are not on this response. So the split below uses the status
// where it is enough, and the outcome this session recorded (from the approve/reject
// response, which does carry the decisions) where it is not. A request decided before the
// page loaded lands in "decided" — truthfully unsorted rather than guessed at.

import type { Tone } from "@/components/dashboard/StatusBadge";
import { categoryLabel } from "@pulseos/ui";
import { formatInstantDate, formatRelativeTime } from "@pulseos/ui";

import type { AccessRequest, DecisionOutcome } from "./api";

/** Which section of the page a request belongs in. */
export type RequestBucket =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  /** Decided, but before this session — the inbox cannot say which way. */
  | "decided"
  /** Withdrawn by the clinician who raised it. */
  | "withdrawn";

/** What one approve/reject call turned out to be, as the page remembers it. */
export type RecordedOutcome = "approved" | "rejected";

/** Shown when the identity projection has no staff row to name. */
export const UNKNOWN_CLINICIAN = "Clinician not identified";
export const UNKNOWN_HOSPITAL = "Hospital not identified";

export interface ConsentRequestView {
  id: string;
  /** The hospital the request was raised under. */
  hospital: string;
  /** The clinician who asked, with their specialty when the record carries one. */
  clinician: string;
  purpose: string;
  /** Category display names, in the order the request listed their codes. */
  categories: readonly string[];
  /** The codes themselves — what an answer must send back, unaltered. */
  categoryCodes: readonly string[];
  /** "2 hours ago". */
  requestedAgo: string;
  /** "22 Aug 2026". */
  requestedOn: string;
  /** When the request itself lapses if left unanswered. Never a grant duration — the API
   * does not say how long access would last until the moment it is granted. */
  expiresOn: string;
  bucket: RequestBucket;
  statusLabel: string;
  statusTone: Tone;
}

const BADGES: Readonly<Record<RequestBucket, { label: string; tone: Tone }>> = {
  pending: { label: "Pending", tone: "warning" },
  approved: { label: "Approved", tone: "success" },
  rejected: { label: "Declined", tone: "destructive" },
  expired: { label: "Expired", tone: "neutral" },
  decided: { label: "Answered", tone: "info" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
};

/** The clinician line: name, plus specialty when the staff row carries one. */
export function clinicianLine(request: AccessRequest): string {
  const requester = request.requester;
  if (requester === null) {
    return UNKNOWN_CLINICIAN;
  }
  const specialty = requester.specialty?.trim();
  return specialty === undefined || specialty.length === 0
    ? requester.fullName
    : `${requester.fullName} · ${specialty}`;
}

/** The hospital the request was raised under; the requester's own is the fallback. */
export function hospitalLine(request: AccessRequest): string {
  return request.requesterHospitalName ?? request.requester?.hospitalName ?? UNKNOWN_HOSPITAL;
}

/**
 * Which section a request belongs in.
 *
 * The recorded outcome wins over the fetched status, because it is newer: the row was
 * PENDING when the page loaded it and the patient has answered it since.
 */
export function bucketFor(
  request: AccessRequest,
  outcomes: ReadonlyMap<string, RecordedOutcome>,
): RequestBucket {
  const recorded = outcomes.get(request.id);
  if (recorded !== undefined) {
    return recorded;
  }
  switch (request.status) {
    case "PENDING":
      return "pending";
    case "EXPIRED":
      return "expired";
    case "CANCELLED":
      return "withdrawn";
    case "DECIDED":
      return "decided";
  }
}

export function toRequestView(
  request: AccessRequest,
  labels: ReadonlyMap<string, string>,
  outcomes: ReadonlyMap<string, RecordedOutcome>,
  now: number = Date.now(),
): ConsentRequestView {
  const bucket = bucketFor(request, outcomes);
  const badge = BADGES[bucket];
  return {
    id: request.id,
    hospital: hospitalLine(request),
    clinician: clinicianLine(request),
    purpose: request.purpose,
    categories: request.categoryCodes.map((code) => categoryLabel(labels, code)),
    categoryCodes: request.categoryCodes,
    requestedAgo: formatRelativeTime(request.createdAt, now),
    requestedOn: formatInstantDate(request.createdAt),
    expiresOn: formatInstantDate(request.expiresAt),
    bucket,
    statusLabel: badge.label,
    statusTone: badge.tone,
  };
}

export type RequestBuckets = Readonly<Record<RequestBucket, readonly ConsentRequestView[]>>;

const EMPTY_BUCKETS: RequestBuckets = {
  pending: [],
  approved: [],
  rejected: [],
  expired: [],
  decided: [],
  withdrawn: [],
};

/** Every request, mapped once and filed under its section. The API returns them newest
 * first and that order is preserved inside each section. */
export function groupRequests(
  requests: readonly AccessRequest[],
  labels: ReadonlyMap<string, string>,
  outcomes: ReadonlyMap<string, RecordedOutcome>,
  now: number = Date.now(),
): RequestBuckets {
  const grouped: Record<RequestBucket, ConsentRequestView[]> = {
    pending: [],
    approved: [],
    rejected: [],
    expired: [],
    decided: [],
    withdrawn: [],
  };
  for (const request of requests) {
    const view = toRequestView(request, labels, outcomes, now);
    grouped[view.bucket].push(view);
  }
  return grouped;
}

export const NO_REQUESTS: RequestBuckets = EMPTY_BUCKETS;

/**
 * What the API says one answer turned out to be.
 *
 * Read from the decisions it returned rather than from the button that was pressed: the
 * response is the authority on what was recorded. `null` means the request is still open —
 * only possible if some requested category went unanswered, in which case the page has
 * nothing to file yet and reloads instead.
 */
export function recordedOutcome(outcome: DecisionOutcome): RecordedOutcome | null {
  if (outcome.requestStatus !== "DECIDED") {
    return null;
  }
  return outcome.decisions.some((decision) => decision.status === "APPROVED")
    ? "approved"
    : "rejected";
}

/** Copy for the standing informational card. */
export const CONSENT_GUIDANCE = {
  title: "Consent Information",
  body:
    "Grant access only when necessary. Hospitals will only be able to view the records " +
    "included in your approval, for as long as the approval lasts.",
  points: [
    "Approvals cover the specific record categories listed — nothing else.",
    "You can withdraw access at any time from Active Grants; it takes effect immediately.",
    "Every time a record of yours is opened, it is recorded in your Audit History.",
  ],
} as const;
