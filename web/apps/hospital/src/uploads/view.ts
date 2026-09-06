// Backend record rows → what the Uploaded Records screens render. Pure functions, no React.
//
// The record vocabulary itself lives in @pulseos/ui (origin, hospital, file type, processing
// state, and the whole detail mapping), so this file adds only what the *listing* needs and
// re-exports the rest. That is why a card and the page it opens can never describe one
// record differently.
//
// **What this listing cannot show, and does not fake: whose record it is.**
// `RecordMetadataResponse` carries no patient identifier — not a Health ID, not a name, not
// an opaque id — so there is no honest way to label a row with its patient, and inventing
// one is worse than omitting it. The screens say so in words rather than leaving a reader to
// assume the omission is a bug.

import {
  formatCalendarDate,
  formatInstantDate,
  originLabel,
  processingLabel,
  processingTone,
} from "@pulseos/ui";
import type { StatusTone } from "@pulseos/ui";

import type { RecordMetadata, RecordPage } from "./api";

// The record vocabulary belongs to the record, not to one screen. Re-exported because this
// module is where the feature's components and tests import everything they render.
export {
  descriptionOf,
  fileTypeLabel,
  hospitalLabel,
  NO_DESCRIPTION,
  originLabel,
  PATIENT_UPLOADED,
  processingLabel,
  processingTone,
  toRecordDetailView,
  UNKNOWN_HOSPITAL,
  type RecordDetailView,
} from "@pulseos/ui";

/** Said once, on the listing and on the detail page, so the absence reads as a property of
 * the API rather than as a missing column. */
export const NO_PATIENT_SHOWN =
  "PulseOS does not return the patient's identity on a record, so uploads cannot be listed " +
  "by patient here.";

export interface UploadRecordView {
  /** Used as a list key and to open the record. */
  id: string;
  /** The short code, for the badge. */
  categoryCode: string;
  /** The vocabulary's display name — the record's title on the card. */
  categoryName: string;
  /** "1 Mar 2026" — when the care happened. Formatted in UTC; it is a calendar date. */
  dateOfService: string;
  /** "4 Sep 2026" — when it reached PulseOS, which is rarely the same day. */
  uploadedOn: string;
  origin: string;
  /** The document's own name. Present here because a hospital reading back its own upload
   * is disclosed the whole record — unlike a clinician's granted listing, which withholds
   * it (ADR-020) until a single authorized read. */
  fileName: string;
  processingLabel: string;
  processingTone: StatusTone;
}

export function toUploadRecordView(record: RecordMetadata): UploadRecordView {
  return {
    id: record.id,
    categoryCode: record.categoryCode,
    categoryName: record.categoryDisplayName,
    dateOfService: formatCalendarDate(record.dateOfService),
    uploadedOn: formatInstantDate(record.createdAt),
    origin: originLabel(record.origin),
    fileName: record.originalFilename,
    processingLabel: processingLabel(record.processingStatus),
    processingTone: processingTone(record.processingStatus),
  };
}

/**
 * The page's records, in the order the API returned them.
 *
 * Deliberately not re-sorted. The API orders newest-added first and a page can be truncated
 * at {@link MAX_PAGE_SIZE}; re-sorting a partial page by service date would put an old
 * record at the top and imply it was the most recent thing this hospital uploaded, which is
 * exactly the wrong thing to tell an administrator checking that a document landed. The
 * order stays the server's until a pager exists to make the whole set available.
 */
export function toUploadRecordViews(
  records: readonly RecordMetadata[],
): readonly UploadRecordView[] {
  return records.map(toUploadRecordView);
}

/**
 * What the page renders, given a loaded response.
 *
 * Two outcomes, not one list that might be empty: an empty page is a state with its own
 * words ("nothing uploaded yet"), and a caller cannot render an empty list by accident
 * because the variants are separate.
 */
export type UploadsOutcome =
  | { kind: "empty" }
  | {
      kind: "loaded";
      records: readonly UploadRecordView[];
      /** True when this hospital has more uploads than one page holds. */
      truncated: boolean;
    };

export function outcomeFor(page: RecordPage): UploadsOutcome {
  if (page.items.length === 0) {
    return { kind: "empty" };
  }
  return {
    kind: "loaded",
    records: toUploadRecordViews(page.items),
    truncated: page.nextCursor !== null,
  };
}

/** "3 records" / "1 record". */
export function recordCountLabel(count: number): string {
  return `${count} record${count === 1 ? "" : "s"}`;
}
