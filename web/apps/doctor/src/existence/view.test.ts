import { expect, test } from "vitest";

import type { RecordCategory } from "./api";
import {
  categoryNames,
  INVALID_HEALTH_ID,
  looksLikeHealthId,
  normalizeHealthId,
  outcomeFor,
} from "./view";

const CATEGORIES: RecordCategory[] = [
  { code: "CBC", displayName: "Complete Blood Count" },
  { code: "MRI", displayName: "MRI Scan" },
];

test("a desk-typed Health ID is normalised the way the backend stores it", () => {
  expect(normalizeHealthId("  phi-ind-2026-1qe8dvr ")).toBe("PHI-IND-2026-1QE8DVR");
});

test("the format check accepts a well-formed ID and rejects a typo", () => {
  expect(looksLikeHealthId("PHI-IND-2026-1QE8DVR")).toBe(true);
  expect(looksLikeHealthId("  phi-ind-2026-1qe8dvr ")).toBe(true);
  expect(looksLikeHealthId("PHI-IND-2026-1QE8DV")).toBe(false); // too short
  expect(looksLikeHealthId("PHI-IND-26-1QE8DVR")).toBe(false); // two-digit year
  expect(looksLikeHealthId("ABC-IND-2026-1QE8DVR")).toBe(false); // wrong prefix
  expect(looksLikeHealthId("")).toBe(false);
});

test("the format check is shape-only — the server owns the check character", () => {
  // Same shape, wrong ISO 7064 check character: this passes here and the server rejects it,
  // which is the intended split (the algorithm lives in one language, not two).
  expect(looksLikeHealthId("PHI-IND-2026-1QE8DVZ")).toBe(true);
});

test("the invalid-input message names the format", () => {
  expect(INVALID_HEALTH_ID).toContain("PHI-IND-YYYY-XXXXXXC");
});

test("categories found is a different outcome from none found", () => {
  expect(outcomeFor("PHI-IND-2026-1QE8DVR", CATEGORIES)).toEqual({
    kind: "found",
    healthId: "PHI-IND-2026-1QE8DVR",
    categories: CATEGORIES,
  });
  expect(outcomeFor("PHI-IND-2026-1QE8DVR", [])).toEqual({
    kind: "none",
    healthId: "PHI-IND-2026-1QE8DVR",
  });
});

test("only display names reach the screen — never codes or anything else", () => {
  expect(categoryNames(CATEGORIES)).toEqual(["Complete Blood Count", "MRI Scan"]);
});
