// Backend consent grants → what the Active Grants page renders.
//
// All of the page's logic lives here: grouping, bucketing, badges, labels and dates. Pure
// functions, no React, so every rule below is unit-testable.
//
// **The API returns one grant per category; the page shows one card per approval.** That is
// the central mapping. A patient who approved three categories at once has three grant rows
// with the same grantee, the same moment of granting and the same expiry — one decision,
// three rows — and showing them as three cards would misrepresent what they did. Grouping
// re-assembles them, using only fields the API actually returns.

import type { Tone } from "@/components/dashboard/StatusBadge";
import { formatInstantDate } from "@/lib/dates";
import { categoryLabel } from "@/lib/recordCategories";

import type { Grant, GrantStatus } from "./api";

/** A grant carries no purpose: purpose belongs to the access request that produced it, and
 * the grant exposes no link back to it. Stated rather than invented. */
export const PURPOSE_UNAVAILABLE = "Not recorded on the grant";

/** Shown when the identity projection has no staff row to name. */
export const UNKNOWN_CLINICIAN = "Clinician not identified";
export const UNKNOWN_HOSPITAL = "Hospital not identified";

/** A grant lapsing within this many days is "expiring soon". */
export const EXPIRING_SOON_DAYS = 7;

const DAY_MS = 24 * 60 * 60 * 1000;

export interface GrantGroupView {
  /** The grouping key — stable across renders, and what per-card state is filed under. */
  id: string;
  /** Every grant row this card stands for. Revoking the card revokes all of them. */
  grantIds: readonly string[];
  hospital: string;
  clinician: string;
  /** Category display names, in the order the API listed the rows. */
  categories: readonly string[];
  /** Null when the API has nothing to say — see PURPOSE_UNAVAILABLE. */
  purpose: string | null;
  grantedOn: string;
  expiresOn: string;
  status: GrantStatus;
  statusLabel: string;
  statusTone: Tone;
  /** Whole days until expiry; null unless the grant is still active. */
  daysRemaining: number | null;
  expiringSoon: boolean;
  /** The compact card's two facts, already worded for this grant's status. */
  summaryNote: string;
  summaryDetail: string;
}

const BADGES: Readonly<Record<GrantStatus, { label: string; tone: Tone }>> = {
  ACTIVE: { label: "Active", tone: "success" },
  REVOKED: { label: "Revoked", tone: "destructive" },
  EXPIRED: { label: "Expired", tone: "neutral" },
};

/**
 * The grouping key: the grantee, the moment access was granted, the moment it lapses — and
 * the status.
 *
 * The first three are what the task calls a logical grant: rows sharing them came from one
 * approval. Status joins them because a card carries one badge and one Revoke button, so a
 * half-withdrawn approval must not collapse into a card that claims to be wholly active.
 * Withdraw one category of three and the page truthfully shows two cards. Every part of the
 * key is a field the API returns; nothing here is inferred.
 */
export function groupKey(grant: Grant): string {
  return [grant.granteeDoctorId, grant.grantedAt, grant.expiresAt, grant.status].join("|");
}

function clinicianLine(grant: Grant): string {
  const grantee = grant.grantee;
  if (grantee === null) {
    return UNKNOWN_CLINICIAN;
  }
  const specialty = grantee.specialty?.trim();
  return specialty === undefined || specialty.length === 0
    ? grantee.fullName
    : `${grantee.fullName} · ${specialty}`;
}

/** Whole days from `now` to `expiresAt`, rounded up: a grant lapsing in six hours has one
 * day left, not zero. Negative once the deadline has passed. */
export function daysUntil(expiresAt: string, now: number): number | null {
  const deadline = new Date(expiresAt).getTime();
  if (Number.isNaN(deadline)) {
    return null;
  }
  return Math.ceil((deadline - now) / DAY_MS);
}

function summaryFor(
  status: GrantStatus,
  grant: Grant,
  daysRemaining: number | null,
): { note: string; detail: string } {
  if (status === "REVOKED") {
    const revokedAt = grant.revokedAt;
    return {
      note: revokedAt === null ? "Withdrawn" : `Withdrawn ${formatInstantDate(revokedAt)}`,
      detail: `Granted ${formatInstantDate(grant.grantedAt)}`,
    };
  }
  if (status === "EXPIRED") {
    return {
      note: `Lapsed ${formatInstantDate(grant.expiresAt)}`,
      detail: `Granted ${formatInstantDate(grant.grantedAt)}`,
    };
  }
  const days = daysRemaining ?? 0;
  return {
    note: `${days} ${days === 1 ? "day" : "days"} remaining`,
    detail: `Expires ${formatInstantDate(grant.expiresAt)}`,
  };
}

/**
 * One card per logical grant, in the order the API returned the rows.
 *
 * `labels` renders category codes as words; a code this build has never seen renders as
 * itself. Grouping is first-seen order, so the API's newest-first ordering survives.
 */
export function groupGrants(
  grants: readonly Grant[],
  labels: ReadonlyMap<string, string>,
  now: number = Date.now(),
): readonly GrantGroupView[] {
  const groups = new Map<string, { first: Grant; ids: string[]; categories: string[] }>();
  for (const grant of grants) {
    const key = groupKey(grant);
    const existing = groups.get(key);
    if (existing === undefined) {
      groups.set(key, { first: grant, ids: [grant.id], categories: [grant.categoryCode] });
      continue;
    }
    existing.ids.push(grant.id);
    existing.categories.push(grant.categoryCode);
  }

  return [...groups].map(([id, group]) => {
    const grant = group.first;
    const badge = BADGES[grant.status];
    const daysRemaining = grant.status === "ACTIVE" ? daysUntil(grant.expiresAt, now) : null;
    const summary = summaryFor(grant.status, grant, daysRemaining);
    return {
      id,
      grantIds: group.ids,
      hospital: grant.grantee?.hospitalName ?? UNKNOWN_HOSPITAL,
      clinician: clinicianLine(grant),
      categories: group.categories.map((code) => categoryLabel(labels, code)),
      purpose: null,
      grantedOn: formatInstantDate(grant.grantedAt),
      expiresOn: formatInstantDate(grant.expiresAt),
      status: grant.status,
      statusLabel: badge.label,
      statusTone: badge.tone,
      daysRemaining,
      expiringSoon:
        grant.status === "ACTIVE" &&
        daysRemaining !== null &&
        daysRemaining <= EXPIRING_SOON_DAYS &&
        daysRemaining >= 0,
      summaryNote: summary.note,
      summaryDetail: summary.detail,
    };
  });
}

/**
 * The rows, with anything withdrawn in this session shown as withdrawn.
 *
 * Applied before grouping, so a card whose rows have all been revoked simply lands in a
 * different group — the status is part of the grouping key. That is what moves a card from
 * Active to Revoked without refetching, and it keeps the page's memory of a withdrawal in
 * one place instead of on the view models.
 */
export function applyRevocations(
  grants: readonly Grant[],
  revokedIds: ReadonlySet<string>,
  revokedAt: string,
): readonly Grant[] {
  if (revokedIds.size === 0) {
    return grants;
  }
  return grants.map((grant) =>
    grant.status === "ACTIVE" && revokedIds.has(grant.id)
      ? { ...grant, status: "REVOKED", revokedAt }
      : grant,
  );
}

export interface GrantBuckets {
  active: readonly GrantGroupView[];
  /** A filtered view of `active`, not a copy: the same objects appear in both. */
  expiringSoon: readonly GrantGroupView[];
  revoked: readonly GrantGroupView[];
  expired: readonly GrantGroupView[];
}

export const NO_GRANTS: GrantBuckets = {
  active: [],
  expiringSoon: [],
  revoked: [],
  expired: [],
};

/**
 * The page's four sections.
 *
 * `expiringSoon` filters `active` rather than mapping it again, so a grant close to lapsing
 * is one object referenced from two lists — which is why revoking it from either place
 * updates both.
 */
export function bucketGrants(groups: readonly GrantGroupView[]): GrantBuckets {
  const active = groups.filter((group) => group.status === "ACTIVE");
  return {
    active,
    expiringSoon: active.filter((group) => group.expiringSoon),
    revoked: groups.filter((group) => group.status === "REVOKED"),
    expired: groups.filter((group) => group.status === "EXPIRED"),
  };
}

/** Copy for the standing privacy card. */
export const PRIVACY_REMINDER = {
  title: "Privacy Reminder",
  body:
    "You can revoke access at any time. Once revoked, healthcare providers will " +
    "immediately lose access to the shared records.",
  points: [
    "A grant only ever covers the record categories listed on it.",
    "Access lapses on its own at the expiry date — you do not need to do anything.",
    "Every record a provider opens is written to your Audit History.",
  ],
} as const;
