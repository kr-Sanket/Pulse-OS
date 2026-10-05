// Backend granted records → what the records screen renders. Pure functions, no React.
//
// Every string the cards show is worded here, so the components stay dumb and each rule is
// unit-tested. Two things in particular live here rather than in JSX:
//
//   • the difference between "you have no grant" and "your grant covers nothing yet",
//     which the API distinguishes through `grantedCategories` and a page must never merge;
//   • the two date formats, which are not interchangeable — `dateOfService` is a calendar
//     date with no zone and `createdAt` is an instant, so formatting them the same way
//     would slip the service date a day for readers west of Greenwich.

import type { RecordCategory } from "@pulseos/ui";
import { formatCalendarDate, formatInstantDate } from "@pulseos/ui";

import { hospitalLabel, originLabel } from "@/record/view";

import type { GrantedRecord, GrantedRecordPage } from "./api";

// How a record's origin and uploading hospital are worded belongs to the record itself, not
// to one screen that lists them: record/view.ts owns that vocabulary and the detail page
// uses the same two functions, so a card and the page it opens cannot describe one record
// two ways. Re-exported because this module is where the listing's components and tests
// import everything they render.
export { hospitalLabel, originLabel, PATIENT_UPLOADED, UNKNOWN_HOSPITAL } from "@/record/view";

export interface GrantedRecordView {
  /** Used as a list key and, in a later slice, to open the record. Never rendered: an id
   * is addressing, not information, and this page shows a clinician nothing it does not
   * need to choose with. */
  id: string;
  /** The short code, for the badge. */
  categoryCode: string;
  /** The vocabulary's display name — the record's title on the card. */
  categoryName: string;
  /** "1 Mar 2026" — when the care happened. Formatted in UTC; it is a calendar date. */
  dateOfService: string;
  origin: string;
  hospital: string;
  /** "4 Sep 2026" — when it reached PulseOS, which is rarely the same day. */
  addedOn: string;
}

export function toGrantedRecordView(record: GrantedRecord): GrantedRecordView {
  return {
    id: record.id,
    categoryCode: record.categoryCode,
    categoryName: record.categoryDisplayName,
    dateOfService: formatCalendarDate(record.dateOfService),
    origin: originLabel(record.origin),
    hospital: hospitalLabel(record.uploadedByHospital, record.origin),
    addedOn: formatInstantDate(record.createdAt),
  };
}

/**
 * The page's records, in the order the API returned them.
 *
 * Deliberately not re-sorted. The API orders newest-added first, and a page can be
 * truncated at {@link MAX_PAGE_SIZE}; re-sorting a partial page by service date would put
 * an old record at the top and imply it was the most recent thing about this patient,
 * which is exactly the wrong thing to tell a clinician. The order stays the server's until
 * a pager exists to make the whole set available.
 */
export function toGrantedRecordViews(
  records: readonly GrantedRecord[],
): readonly GrantedRecordView[] {
  return records.map(toGrantedRecordView);
}

/** The category names a grant covers, in the vocabulary order the API returned them. */
export function grantedCategoryNames(categories: readonly RecordCategory[]): readonly string[] {
  return categories.map((category) => category.displayName);
}

/**
 * What the page renders, given a loaded response.
 *
 * Three outcomes, never two. "Nothing was approved" and "what was approved is empty" look
 * identical in `items` and are completely different situations — one needs an access
 * request, the other needs nothing at all — so the scope decides which, and a caller cannot
 * collapse them by accident because they are separate variants.
 */
export type GrantedRecordsOutcome =
  | { kind: "no-grant" }
  | { kind: "granted-empty"; categories: readonly string[]; patientId: string }
  | {
      kind: "loaded";
      categories: readonly string[];
      records: readonly GrantedRecordView[];
      /** True when the patient has more granted records than one page holds. */
      truncated: boolean;
      patientId: string;
    };

export function outcomeFor(page: GrantedRecordPage): GrantedRecordsOutcome {
  const categories = grantedCategoryNames(page.grantedCategories);
  if (categories.length === 0) {
    // The scope is empty, so `items` is necessarily empty too — the API cannot return a
    // record outside a granted category.
    return { kind: "no-grant" };
  }
  if (page.items.length === 0) {
    return { kind: "granted-empty", categories, patientId: page.patientId };
  }
  return {
    kind: "loaded",
    categories,
    records: toGrantedRecordViews(page.items),
    truncated: page.nextCursor !== null,
    patientId: page.patientId,
  };
}

/** True when the clinician holds a live grant for this patient — the one condition that
 * makes a link to this page worth showing at all. */
export function hasGrant(page: GrantedRecordPage): boolean {
  return page.grantedCategories.length > 0;
}

/** "3 records" / "1 record". */
export function recordCountLabel(count: number): string {
  return `${count} record${count === 1 ? "" : "s"}`;
}

/** "CBC and MRI" / "CBC, MRI and X-Ray" — the scope read as a sentence fragment. */
export function joinCategories(names: readonly string[]): string {
  if (names.length <= 1) {
    return names[0] ?? "";
  }
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
