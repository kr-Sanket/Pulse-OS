// Health ID input → what the search screen renders. Pure functions, no React.
//
// The API returns a code and a display name per category and nothing else (no counts, no
// filenames, no hospitals, no dates), so there is very little to map — which is the point.
// What lives here is the input normalisation and the shape of each outcome.

import type { RecordCategory } from "./api";

/** ADR-012 stores canonical uppercase; a reception desk types whatever it types. */
export function normalizeHealthId(input: string): string {
  return input.trim().toUpperCase();
}

/**
 * Format-only check: the prefix, a four-digit year, and seven characters of body plus
 * check character.
 *
 * Deliberately *not* the ISO 7064 check-character verification the backend performs. That
 * algorithm lives in one place (app/modules/patients/health_id.py); reimplementing it in
 * TypeScript would be a second copy free to drift. This catches a typo before a round
 * trip; the server remains the authority on whether an ID is real.
 */
const HEALTH_ID_SHAPE = /^PHI-IND-\d{4}-[0-9A-Z]{7}$/;

export function looksLikeHealthId(input: string): boolean {
  return HEALTH_ID_SHAPE.test(normalizeHealthId(input));
}

export const INVALID_HEALTH_ID =
  "That is not a Pulse Health ID. The format is PHI-IND-YYYY-XXXXXXC.";

/** What the results area shows, given a completed search. */
export type SearchOutcome =
  | { kind: "idle" }
  | { kind: "searching" }
  | { kind: "found"; healthId: string; categories: readonly RecordCategory[] }
  | { kind: "none"; healthId: string }
  | { kind: "error"; message: string };

/** A successful response splits into "has records" and "has none" — both are answers, and
 * only the second is an empty state rather than a failure. */
export function outcomeFor(healthId: string, categories: readonly RecordCategory[]): SearchOutcome {
  return categories.length === 0
    ? { kind: "none", healthId }
    : { kind: "found", healthId, categories };
}

/** The category names to display, in the order the API returned them (vocabulary order). */
export function categoryNames(categories: readonly RecordCategory[]): readonly string[] {
  return categories.map((category) => category.displayName);
}
