// Backend record metadata → what the cards and the details panel actually render.
//
// Pure functions, no React: the API speaks codes, bytes and ISO dates, the UI speaks
// icons, "2.4 MB" and "24 Aug 2026". Keeping the translation here is what lets the
// presentation components stay dumb, and makes every rule below unit-testable.

import { FileText, FlaskConical, Pill, ScanLine, Syringe, type LucideIcon } from "lucide-react";

import type { Tone } from "@/components/dashboard/StatusBadge";

import type { RecordMetadata, RecordSort } from "./api";

export interface CategoryStyle {
  icon: LucideIcon;
  tone: Tone;
}

/** Keyed by the codes GET /record-categories publishes. Unknown codes fall back rather
 * than throwing, so a category added server-side renders without a frontend release. */
const CATEGORY_STYLES: Readonly<Record<string, CategoryStyle>> = {
  CBC: { icon: FlaskConical, tone: "info" },
  LAB_REPORT: { icon: FlaskConical, tone: "info" },
  MRI: { icon: ScanLine, tone: "primary" },
  XRAY: { icon: ScanLine, tone: "primary" },
  CT_SCAN: { icon: ScanLine, tone: "primary" },
  ULTRASOUND: { icon: ScanLine, tone: "primary" },
  PRESCRIPTION: { icon: Pill, tone: "success" },
  DISCHARGE_SUMMARY: { icon: FileText, tone: "warning" },
  VACCINATION: { icon: Syringe, tone: "success" },
  OTHER: { icon: FileText, tone: "neutral" },
};

const FALLBACK_STYLE: CategoryStyle = { icon: FileText, tone: "neutral" };

export function categoryStyle(code: string): CategoryStyle {
  return CATEGORY_STYLES[code] ?? FALLBACK_STYLE;
}

// Date and size formatting are portal-wide and live in the shared package; re-exported
// here because the records components and their tests import everything they render
// through this module.
export { formatCalendarDate, formatFileSize, formatInstantDate, todayIsoDate } from "@pulseos/ui";

/** Who the record came from. A locker upload has no hospital — the patient added it. */
export function providerLabel(record: RecordMetadata): string {
  return record.uploadedByHospital?.name ?? "Your locker";
}

/** The heading on the card and the panel. The API models no title: a document is named by
 * its file, and `description` is the sentence underneath it. */
export function recordTitle(record: RecordMetadata): string {
  return record.originalFilename;
}

export const NO_DESCRIPTION = "No description was recorded for this document.";

export function recordDescription(record: RecordMetadata): string {
  const description = record.description?.trim();
  return description === undefined || description.length === 0 ? NO_DESCRIPTION : description;
}

// -- visibility -----------------------------------------------------------------------
//
// Hiding withdraws a record from what consent can share. What it does *not* do is the part
// the wording has to carry: the hospital that uploaded a record keeps its own access
// (ADR-013 layer 2), so a badge reading "Private" or copy promising "no one else can see
// this" would state a guarantee the authorization model does not give.

/** The badge on a hidden record, on both the card and the panel. */
export const HIDDEN_BADGE = "Hidden";

/** The panel's button, worded as the action it performs rather than the state it leaves. */
export const HIDE_ACTION = "Hide from doctors";
export const UNHIDE_ACTION = "Unhide";
export const HIDING_LABEL = "Hiding…";
export const UNHIDING_LABEL = "Unhiding…";

/** One line under the button. Precise about the exception rather than silent about it. */
export const HIDDEN_EXPLANATION =
  "Hidden records are not shown to doctors, even where you have approved access. " +
  "The hospital that uploaded a record can still see it, and you always can.";

export function visibilityActionLabel(isHidden: boolean, busy: boolean): string {
  if (busy) {
    return isHidden ? UNHIDING_LABEL : HIDING_LABEL;
  }
  return isHidden ? UNHIDE_ACTION : HIDE_ACTION;
}

/**
 * The rows, with any visibility changed in this session shown as changed.
 *
 * The same shape as `applyRevocations` on the grants page, and for the same reason: the
 * listing is one keyset sequence with a cursor, so refetching it to reflect a one-record
 * change would drop every page "Load more" has appended. The overlay is keyed by record id,
 * so it survives paging; the page drops it whenever the base listing reloads, which is what
 * keeps the server authoritative.
 */
export function applyVisibility(
  records: readonly RecordMetadata[],
  overrides: ReadonlyMap<string, boolean>,
): readonly RecordMetadata[] {
  if (overrides.size === 0) {
    return records;
  }
  return records.map((record) => applyVisibilityTo(record, overrides));
}

/** The same rule for a single record — what the details panel reads. Returns the record
 * itself, not a copy, when nothing about it changed. */
export function applyVisibilityTo(
  record: RecordMetadata,
  overrides: ReadonlyMap<string, boolean>,
): RecordMetadata {
  const isHidden = overrides.get(record.id);
  return isHidden === undefined || isHidden === record.isHidden ? record : { ...record, isHidden };
}

// -- listing controls ---------------------------------------------------------------
//
// Sorting, filtering and searching all happen server-side. They used to be partly
// client-side, which was wrong in a way that got worse with real data: the page asked for
// 100 records and searched only those, so a patient with more than a hundred was told
// "no results" for a record that existed. The API now owns all three, and this module owns
// only the vocabulary and the reset rule.

export type { RecordSort };

export const SORT_OPTIONS: readonly { value: RecordSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
];

export const DEFAULT_SORT: RecordSort = "newest";

/** Everything the listing query is made of. A cursor is only valid for one of these. */
export interface RecordQuery {
  category: string | null;
  search: string;
  sort: RecordSort;
}

export const EMPTY_QUERY: RecordQuery = { category: null, search: "", sort: DEFAULT_SORT };

/** Whether "Clear filters" would change anything — the control hides when it would not. */
export function hasActiveFilters(query: RecordQuery): boolean {
  return query.category !== null || query.search.trim().length > 0 || query.sort !== DEFAULT_SORT;
}

/**
 * Whether a cursor held for `previous` may still be used for `next`.
 *
 * A cursor addresses a position in one specific sequence. Change the sort and the sequence
 * runs the other way; change the search or the category and it contains different records.
 * The backend refuses a cursor whose sort disagrees, but it cannot detect a changed search
 * — that page would simply be wrong — so the client resets on any of the three.
 */
export function keepsCursor(previous: RecordQuery, next: RecordQuery): boolean {
  return (
    previous.category === next.category &&
    previous.search.trim() === next.search.trim() &&
    previous.sort === next.sort
  );
}

/** The search term as the API should receive it: trimmed, and absent rather than empty. */
export function searchParam(query: RecordQuery): string | null {
  const trimmed = query.search.trim();
  return trimmed.length === 0 ? null : trimmed;
}
