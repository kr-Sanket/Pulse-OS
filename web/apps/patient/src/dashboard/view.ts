// Backend page data → what the dashboard renders.
//
// The dashboard summarises five pages, so it maps nothing itself that those pages already
// map: the action vocabulary comes from audit/view.ts, grant grouping from grants/view.ts,
// requester lines from consent/view.ts, record styling from records/view.ts. What is left —
// and what lives here — is how those views become dashboard widgets, and how the figures
// are counted.
//
// **Every figure is over loaded data only.** There is no aggregate endpoint, so a count is
// a count of what one page returned. Each figure's note says so whenever the page was
// truncated, and no label claims a lifetime total.

import { Activity, FileText, IdCard, KeyRound, ShieldCheck, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { AuditEvent } from "@/audit/api";
import { toEventView } from "@/audit/view";
import type { AccessRequest } from "@/consent/api";
import { bucketFor, clinicianLine, hospitalLine } from "@/consent/view";
import type { Grant } from "@/grants/api";
import { bucketGrants, groupGrants, type GrantGroupView } from "@/grants/view";
import type { Tone } from "@/components/dashboard/StatusBadge";
import { formatRelativeTime } from "@/lib/dates";
import type { RecordMetadata } from "@/records/api";
import { categoryStyle, formatCalendarDate, providerLabel, recordTitle } from "@/records/view";

/** Greeting fallback when neither the profile nor the identity provider has a name. */
export const GREETING_FALLBACK_NAME = "there";

/** A request lapsing within this many hours is flagged in the review queue. */
const URGENT_WITHIN_HOURS = 24;

/** How many rows each dashboard widget previews before deferring to its page. */
export const RECENT_RECORDS_SHOWN = 4;
export const RECENT_ACTIVITY_SHOWN = 4;
export const EXPIRING_GRANTS_SHOWN = 3;

export type ActivityTone =
  "default" | "secondary" | "destructive" | "primary" | "success" | "warning" | "info" | "neutral";

export interface ActivityEntry {
  id: string;
  title: string;
  description: string;
  icon: LucideIcon;
  /** Trailing relative time, when the row has one. */
  timestamp?: string;
  /** Trailing badge, when the row has one. */
  badgeLabel?: string;
  tone?: ActivityTone;
  /** Internal route the row links to, when it is navigable. */
  to?: string;
}

export interface ReviewRequest {
  id: string;
  requester: string;
  purpose: string;
  urgent: boolean;
}

export interface ExpiringGrant {
  id: string;
  grantee: string;
  /** Category and hospital the grant covers. */
  scope: string;
  expiresIn: string;
  icon: LucideIcon;
}

/** First word of a name, for the greeting. */
export function firstNameOf(fullName: string | null | undefined): string {
  const [first] = (fullName ?? "").trim().split(/\s+/);
  return first !== undefined && first.length > 0 ? first : GREETING_FALLBACK_NAME;
}

// -- recent records ---------------------------------------------------------------------

/** The newest records, styled exactly as the Records page styles them. */
export function toRecordEntries(
  records: readonly RecordMetadata[],
  limit: number = RECENT_RECORDS_SHOWN,
): readonly ActivityEntry[] {
  return records.slice(0, limit).map((record) => {
    const style = categoryStyle(record.categoryCode);
    return {
      id: record.id,
      title: recordTitle(record),
      description: `${providerLabel(record)} · ${formatCalendarDate(record.dateOfService)}`,
      icon: style.icon,
      badgeLabel: record.categoryDisplayName,
      tone: style.tone,
      to: "/records",
    };
  });
}

// -- recent activity --------------------------------------------------------------------

/**
 * The newest trail entries as activity rows.
 *
 * Built on audit/view.ts's own mapping, so the action vocabulary, the tone of each action
 * and the "You" rule for the patient's own events exist once in the app. Only the row
 * layout — which fact goes in which slot — is decided here.
 */
export function toActivityEntries(
  events: readonly AuditEvent[],
  labels: ReadonlyMap<string, string>,
  now: number = Date.now(),
  limit: number = RECENT_ACTIVITY_SHOWN,
): readonly ActivityEntry[] {
  return events.slice(0, limit).map((event) => {
    const view = toEventView(event, labels);
    const detail = [view.actor, view.hasCategory ? view.category : null].filter(
      (part): part is string => part !== null,
    );
    return {
      id: view.id,
      title: view.origin,
      description: detail.length === 0 ? view.date : detail.join(" · "),
      icon: view.icon,
      timestamp: formatRelativeTime(event.occurredAt, now),
      badgeLabel: view.actionLabel,
      tone: view.actionTone,
      to: "/audit",
    };
  });
}

// -- review queue -----------------------------------------------------------------------

/** Only what is actually waiting on the patient, named as the Consent page names it. */
export function toReviewRequests(
  requests: readonly AccessRequest[],
  now: number = Date.now(),
): readonly ReviewRequest[] {
  return requests
    .filter((request) => bucketFor(request, new Map()) === "pending")
    .map((request) => ({
      id: request.id,
      requester: `${clinicianLine(request)} · ${hospitalLine(request)}`,
      purpose: request.purpose,
      // Time-sensitive because the *request* lapses, not because the asker said so: the
      // API carries no priority, and the only urgency in the data is its own deadline.
      urgent: hoursUntil(request.expiresAt, now) <= URGENT_WITHIN_HOURS,
    }));
}

function hoursUntil(iso: string, now: number): number {
  const deadline = new Date(iso).getTime();
  return Number.isNaN(deadline) ? Number.POSITIVE_INFINITY : (deadline - now) / 3_600_000;
}

// -- grants -----------------------------------------------------------------------------

/** The grant cards the Grants page would show, so both pages group identically. */
export function toGrantGroups(
  grants: readonly Grant[],
  labels: ReadonlyMap<string, string>,
  now: number = Date.now(),
): readonly GrantGroupView[] {
  return groupGrants(grants, labels, now);
}

/** The nearest-lapsing active grants, using the Grants page's own "expiring soon" rule. */
export function toExpiringGrants(
  groups: readonly GrantGroupView[],
  limit: number = EXPIRING_GRANTS_SHOWN,
): readonly ExpiringGrant[] {
  return [...bucketGrants(groups).expiringSoon]
    .sort((left, right) => (left.daysRemaining ?? 0) - (right.daysRemaining ?? 0))
    .slice(0, limit)
    .map((group) => ({
      id: group.id,
      grantee: group.clinician,
      scope: `${group.categories.join(", ")} · ${group.hospital}`,
      expiresIn: group.summaryNote,
      icon: KeyRound,
    }));
}

// -- figures ------------------------------------------------------------------------------

export type StatStatus = "loading" | "ready" | "unavailable";

export interface DashboardStat {
  id: string;
  label: string;
  status: StatStatus;
  value: string;
  unit?: string;
  note: string;
  tone: Tone;
  icon: LucideIcon;
}

/** What one figure knows about its source: still loading, failed, or a page of rows. */
export interface StatSource<T> {
  status: "loading" | "ready" | "error";
  items: readonly T[];
  /** True when the API had more rows than the page returned. */
  truncated: boolean;
}

const UNAVAILABLE_NOTE = "Unavailable right now";

function figure(
  id: string,
  label: string,
  icon: LucideIcon,
  tone: Tone,
  source: { status: StatSource<unknown>["status"] },
  ready: () => { value: string; unit?: string; note: string },
): DashboardStat {
  if (source.status === "loading") {
    return { id, label, status: "loading", value: "—", note: "", tone, icon };
  }
  if (source.status === "error") {
    return { id, label, status: "unavailable", value: "—", note: UNAVAILABLE_NOTE, tone, icon };
  }
  return { id, label, status: "ready", ...ready(), tone, icon };
}

/** "In your account" is only true when the page held everything; otherwise say so. */
function scopeNote(truncated: boolean, whole: string): string {
  return truncated ? "Most recent page only" : whole;
}

/**
 * The four figures, each derived from the page its own source returned.
 *
 * Sources are independent: one failing leaves its figure unavailable and the other three
 * intact, which is the same rule the widgets below follow.
 */
export function summarize(sources: {
  records: StatSource<RecordMetadata>;
  requests: StatSource<AccessRequest>;
  grants: StatSource<GrantGroupView>;
  events: StatSource<AuditEvent>;
  now?: number;
}): readonly DashboardStat[] {
  const now = sources.now ?? Date.now();
  const pending = sources.requests.items.filter(
    (request) => bucketFor(request, new Map()) === "pending",
  );
  const buckets = bucketGrants(sources.grants.items);
  const latest = sources.events.items[0];

  return [
    figure("records", "Records", FileText, "info", sources.records, () => ({
      value: `${sources.records.items.length}`,
      note: scopeNote(sources.records.truncated, "In your account"),
    })),
    figure("pending", "Pending requests", ShieldCheck, "warning", sources.requests, () => ({
      value: `${pending.length}`,
      note: pending.length === 0 ? "Nothing waiting on you" : "Needs your review",
    })),
    figure("grants", "Active grants", KeyRound, "success", sources.grants, () => ({
      value: `${buckets.active.length}`,
      note:
        buckets.expiringSoon.length === 0
          ? scopeNote(sources.grants.truncated, "None expiring soon")
          : `${buckets.expiringSoon.length} expiring soon`,
    })),
    figure("activity", "Latest activity", Activity, "neutral", sources.events, () => ({
      value: latest === undefined ? "—" : formatRelativeTime(latest.occurredAt, now),
      note: latest === undefined ? "Nothing recorded yet" : "Most recent entry in your log",
    })),
  ];
}

// -- standing copy ------------------------------------------------------------------------

/** Quick actions are navigation, not data — unchanged from the original dashboard. */
export const QUICK_ACTIONS: readonly {
  id: string;
  title: string;
  description: string;
  actionLabel: string;
  to: string;
  icon: LucideIcon;
}[] = [
  {
    id: "review-requests",
    title: "Review access requests",
    description: "Decide per category which doctors may read your records.",
    actionLabel: "Open requests",
    to: "/consent",
    icon: ShieldCheck,
  },
  {
    id: "upload-record",
    title: "Add to your locker",
    description: "Upload a report you received outside a partner hospital.",
    actionLabel: "Upload a record",
    to: "/records",
    icon: Upload,
  },
  {
    id: "health-id",
    title: "Your Health ID",
    description: "Show your PulseOS ID at a reception desk.",
    actionLabel: "View profile",
    to: "/profile",
    icon: IdCard,
  },
];

/** Copy for the identity hero. The Health ID itself comes from GET /patients/me. */
export const HERO = {
  badgeLabel: "Pulse Health ID",
  footnote: "Show this ID at any PulseOS hospital and your records follow you.",
} as const;
