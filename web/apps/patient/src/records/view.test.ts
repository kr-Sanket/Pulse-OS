import { expect, test } from "vitest";

import type { RecordMetadata } from "./api";
import {
  categoryStyle,
  DEFAULT_SORT,
  EMPTY_QUERY,
  formatCalendarDate,
  formatFileSize,
  hasActiveFilters,
  keepsCursor,
  NO_DESCRIPTION,
  searchParam,
  SORT_OPTIONS,
  applyVisibility,
  applyVisibilityTo,
  HIDE_ACTION,
  HIDING_LABEL,
  providerLabel,
  recordDescription,
  recordTitle,
  todayIsoDate,
  UNHIDE_ACTION,
  UNHIDING_LABEL,
  visibilityActionLabel,
} from "./view";

const RECORD: RecordMetadata = {
  id: "0f1b6c2e-0000-4000-8000-000000000001",
  categoryCode: "CBC",
  categoryDisplayName: "Complete Blood Count",
  origin: "HOSPITAL_UPLOAD",
  dateOfService: "2026-08-24",
  description: "Routine full blood count.",
  originalFilename: "cbc-august.pdf",
  contentType: "application/pdf",
  sizeBytes: 248_000,
  processingStatus: "UPLOADED",
  isHidden: false,
  uploadedByHospital: { hid: "HID-0001", name: "TMH Jamshedpur" },
  createdAt: "2026-08-24T10:00:00Z",
};

function withRecord(overrides: Partial<RecordMetadata>): RecordMetadata {
  return { ...RECORD, ...overrides };
}

test("a known category keeps its own icon and tone, an unknown one falls back", () => {
  expect(categoryStyle("CBC")).not.toEqual(categoryStyle("SOMETHING_NEW"));
  expect(categoryStyle("SOMETHING_NEW").tone).toBe("neutral");
});

test("a calendar date is formatted in UTC, so it never slips a day", () => {
  expect(formatCalendarDate("2026-08-24")).toBe("24 Aug 2026");
  expect(formatCalendarDate("2026-01-01")).toBe("1 Jan 2026");
});

test("an unparseable date is shown verbatim rather than as Invalid Date", () => {
  expect(formatCalendarDate("not-a-date")).toBe("not-a-date");
});

test("file sizes scale from bytes to megabytes", () => {
  expect(formatFileSize(512)).toBe("512 B");
  expect(formatFileSize(2048)).toBe("2 KB");
  expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
});

test("provenance is the uploading hospital, or the patient's own locker", () => {
  expect(providerLabel(RECORD)).toBe("TMH Jamshedpur");
  expect(providerLabel(withRecord({ uploadedByHospital: null }))).toBe("Your locker");
});

test("the title is the document's filename — the API models no title", () => {
  expect(recordTitle(RECORD)).toBe("cbc-august.pdf");
});

test("a missing or blank description falls back to a sentence", () => {
  expect(recordDescription(RECORD)).toBe("Routine full blood count.");
  expect(recordDescription(withRecord({ description: null }))).toBe(NO_DESCRIPTION);
  expect(recordDescription(withRecord({ description: "   " }))).toBe(NO_DESCRIPTION);
});

// -- listing controls ---------------------------------------------------------------

test("the sort vocabulary is the two orderings the API declares, newest by default", () => {
  expect(SORT_OPTIONS.map((option) => option.value)).toEqual(["newest", "oldest"]);
  expect(DEFAULT_SORT).toBe("newest");
  expect(EMPTY_QUERY).toEqual({ category: null, search: "", sort: "newest" });
});

test("clearing is offered only when some filter is actually set", () => {
  expect(hasActiveFilters(EMPTY_QUERY)).toBe(false);
  expect(hasActiveFilters({ ...EMPTY_QUERY, search: "   " })).toBe(false); // whitespace is not a filter
  expect(hasActiveFilters({ ...EMPTY_QUERY, category: "MRI" })).toBe(true);
  expect(hasActiveFilters({ ...EMPTY_QUERY, search: "lipid" })).toBe(true);
  expect(hasActiveFilters({ ...EMPTY_QUERY, sort: "oldest" })).toBe(true);
});

test("a cursor survives only while every part of the query is unchanged", () => {
  expect(keepsCursor(EMPTY_QUERY, EMPTY_QUERY)).toBe(true);
  // Whitespace-only edits do not change the request, so the cursor stays valid.
  expect(
    keepsCursor({ ...EMPTY_QUERY, search: "lipid" }, { ...EMPTY_QUERY, search: "lipid " }),
  ).toBe(true);
  expect(keepsCursor(EMPTY_QUERY, { ...EMPTY_QUERY, sort: "oldest" })).toBe(false);
  expect(keepsCursor(EMPTY_QUERY, { ...EMPTY_QUERY, category: "MRI" })).toBe(false);
  expect(keepsCursor(EMPTY_QUERY, { ...EMPTY_QUERY, search: "lipid" })).toBe(false);
});

test("the search term reaches the API trimmed, and absent rather than empty", () => {
  expect(searchParam(EMPTY_QUERY)).toBeNull();
  expect(searchParam({ ...EMPTY_QUERY, search: "   " })).toBeNull();
  expect(searchParam({ ...EMPTY_QUERY, search: "  lipid  " })).toBe("lipid");
});

test("today is a local calendar date the upload form can use as its ceiling", () => {
  const today = todayIsoDate();
  const now = new Date();

  expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(today).toBe(
    `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(2, "0")}-${`${now.getDate()}`.padStart(2, "0")}`,
  );
});

test("the action names what pressing it will do, not the state the record is in", () => {
  expect(visibilityActionLabel(false, false)).toBe(HIDE_ACTION);
  expect(visibilityActionLabel(true, false)).toBe(UNHIDE_ACTION);
});

test("while a change is in flight the label says which way it is going", () => {
  expect(visibilityActionLabel(false, true)).toBe(HIDING_LABEL);
  expect(visibilityActionLabel(true, true)).toBe(UNHIDING_LABEL);
});

test("an empty overlay leaves the listing exactly as the API sent it", () => {
  const records = [withRecord({ id: "a" }), withRecord({ id: "b" })];

  expect(applyVisibility(records, new Map())).toBe(records);
});

test("an overlay changes the record it names and no other", () => {
  const records = [withRecord({ id: "a" }), withRecord({ id: "b" })];

  const applied = applyVisibility(records, new Map([["a", true]]));

  expect(applied.map((record) => [record.id, record.isHidden])).toEqual([
    ["a", true],
    ["b", false],
  ]);
  // Untouched rows keep their identity, so React re-renders only what changed.
  expect(applied[1]).toBe(records[1]);
});

test("the overlay is a rearrangement of one field and nothing else", () => {
  const record = withRecord({ id: "a", description: "Routine full blood count." });

  const applied = applyVisibilityTo(record, new Map([["a", true]]));

  expect(applied).toEqual({ ...record, isHidden: true });
  // Order and membership of the listing are the page's business, never this function's.
  expect(applyVisibility([record], new Map([["a", true]]))).toHaveLength(1);
});

test("an overlay agreeing with the server is a no-op rather than a new object", () => {
  const record = withRecord({ id: "a", isHidden: true });

  expect(applyVisibilityTo(record, new Map([["a", true]]))).toBe(record);
});

test("an overlay naming a record that is not on the page changes nothing", () => {
  const records = [withRecord({ id: "a" })];

  const applied = applyVisibility(records, new Map([["gone", true]]));

  expect(applied[0]).toBe(records[0]);
});
