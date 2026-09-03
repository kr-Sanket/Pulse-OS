import { expect, test } from "vitest";

import type { RecordMetadata } from "./api";
import {
  categoryStyle,
  formatCalendarDate,
  formatFileSize,
  matchesQuery,
  NO_DESCRIPTION,
  providerLabel,
  recordDescription,
  recordTitle,
  todayIsoDate,
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

test("search matches filename, description, category and provider, case-insensitively", () => {
  expect(matchesQuery(RECORD, "")).toBe(true);
  expect(matchesQuery(RECORD, "   ")).toBe(true);
  expect(matchesQuery(RECORD, "AUGUST")).toBe(true);
  expect(matchesQuery(RECORD, "blood")).toBe(true);
  expect(matchesQuery(RECORD, "jamshedpur")).toBe(true);
  expect(matchesQuery(RECORD, "vellore")).toBe(false);
});

test("today is a local calendar date the upload form can use as its ceiling", () => {
  const today = todayIsoDate();
  const now = new Date();

  expect(today).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(today).toBe(
    `${now.getFullYear()}-${`${now.getMonth() + 1}`.padStart(2, "0")}-${`${now.getDate()}`.padStart(2, "0")}`,
  );
});
