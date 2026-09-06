import { expect, test } from "vitest";

import { formatCalendarDate, formatInstantDate } from "@pulseos/ui";

import type { RecordMetadata, RecordPage } from "./api";
import {
  NO_PATIENT_SHOWN,
  descriptionOf,
  fileTypeLabel,
  hospitalLabel,
  originLabel,
  outcomeFor,
  PATIENT_UPLOADED,
  processingLabel,
  processingTone,
  recordCountLabel,
  toRecordDetailView,
  toUploadRecordView,
  toUploadRecordViews,
  UNKNOWN_HOSPITAL,
} from "./view";

const RECORD: RecordMetadata = {
  id: "rec-1",
  categoryCode: "CBC",
  categoryDisplayName: "Complete Blood Count",
  origin: "HOSPITAL_UPLOAD",
  dateOfService: "2026-03-01",
  description: "Routine pre-operative panel",
  originalFilename: "cbc-report.pdf",
  contentType: "application/pdf",
  sizeBytes: 2_400_000,
  processingStatus: "UPLOADED",
  uploadedByHospital: { hid: "HID-0001", name: "Tata Main Hospital" },
  createdAt: "2026-09-04T09:30:00Z",
};

function withRecord(overrides: Partial<RecordMetadata>): RecordMetadata {
  return { ...RECORD, ...overrides };
}

function pageOf(items: readonly RecordMetadata[], nextCursor: string | null = null): RecordPage {
  return { items: [...items], nextCursor };
}

// -- mapping ---------------------------------------------------------------------------

test("a record row maps to what the card renders", () => {
  const view = toUploadRecordView(RECORD);

  expect(view.id).toBe("rec-1");
  expect(view.categoryCode).toBe("CBC");
  expect(view.categoryName).toBe("Complete Blood Count");
  expect(view.fileName).toBe("cbc-report.pdf");
  expect(view.origin).toBe("Hospital upload");
});

test("the two dates use their own formats, because they are different kinds of value", () => {
  // dateOfService is a zoneless calendar date; createdAt is an instant. Formatting them the
  // same way would slip the service date a day for readers west of Greenwich.
  const view = toUploadRecordView(RECORD);

  expect(view.dateOfService).toBe(formatCalendarDate("2026-03-01"));
  expect(view.uploadedOn).toBe(formatInstantDate("2026-09-04T09:30:00Z"));
  expect(view.dateOfService).not.toBe(view.uploadedOn);
});

test("components are handed formatted values, never raw ones", () => {
  const view = toUploadRecordView(RECORD);

  expect(view.dateOfService).not.toContain("-");
  expect(view.uploadedOn).not.toContain("T");
  expect(typeof view.processingLabel).toBe("string");
});

// -- status wording ---------------------------------------------------------------------

test("processing states are worded as where the document is, not what was done to it", () => {
  // UPLOADED is the only state the backend writes today; the M5 worker adds the rest.
  expect(processingLabel("UPLOADED")).toBe("Stored");
  expect(processingLabel("PROCESSING")).toBe("Being processed");
  expect(processingLabel("INDEXED")).toBe("Indexed");
  expect(processingLabel("FAILED")).toBe("Processing failed");
});

test("processing tones distinguish a failure from a resting state", () => {
  expect(processingTone("UPLOADED")).toBe("neutral");
  expect(processingTone("FAILED")).toBe("destructive");
  expect(processingTone("INDEXED")).toBe("success");
});

test("statuses are read from the API, never inferred from other fields", () => {
  // A record uploaded long ago is still "Stored" if that is what the API says.
  const old = withRecord({ createdAt: "2020-01-01T00:00:00Z", processingStatus: "UPLOADED" });

  expect(toUploadRecordView(old).processingLabel).toBe("Stored");
});

// -- origin and hospital wording ----------------------------------------------------------

test("origin is worded, and a locker record is never called a hospital upload", () => {
  expect(originLabel("HOSPITAL_UPLOAD")).toBe("Hospital upload");
  expect(originLabel("PATIENT_LOCKER")).toBe("Patient locker");
});

test("a missing hospital is explained rather than left blank or invented", () => {
  expect(hospitalLabel(null, "PATIENT_LOCKER")).toBe(PATIENT_UPLOADED);
  expect(hospitalLabel(null, "HOSPITAL_UPLOAD")).toBe(UNKNOWN_HOSPITAL);
  expect(hospitalLabel({ hid: "HID-0001", name: "Tata Main Hospital" }, "HOSPITAL_UPLOAD")).toBe(
    "Tata Main Hospital",
  );
});

test("an unknown content type is shown verbatim rather than guessed at", () => {
  expect(fileTypeLabel("application/pdf")).toBe("PDF");
  expect(fileTypeLabel("application/dicom")).toBe("application/dicom");
});

test("a blank description is null, so the row is omitted instead of filled", () => {
  expect(descriptionOf(withRecord({ description: null }))).toBeNull();
  expect(descriptionOf(withRecord({ description: "   " }))).toBeNull();
  expect(descriptionOf(RECORD)).toBe("Routine pre-operative panel");
});

// -- ordering ---------------------------------------------------------------------------

test("the server's order is preserved, never re-sorted", () => {
  // The API orders newest-added first and the page may be truncated; re-sorting a partial
  // page by service date would put an old record on top and imply it was the most recent.
  const records = [
    withRecord({ id: "a", dateOfService: "2020-01-01" }),
    withRecord({ id: "b", dateOfService: "2026-08-01" }),
    withRecord({ id: "c", dateOfService: "2024-05-05" }),
  ];

  expect(toUploadRecordViews(records).map((view) => view.id)).toEqual(["a", "b", "c"]);
});

// -- outcomes: empty, loaded, truncation ---------------------------------------------------

test("an empty page is its own outcome, so an empty list can never be rendered", () => {
  expect(outcomeFor(pageOf([]))).toEqual({ kind: "empty" });
});

test("a loaded page reports its records and whether more exist", () => {
  const outcome = outcomeFor(pageOf([RECORD]));

  expect(outcome.kind).toBe("loaded");
  if (outcome.kind !== "loaded") return;
  expect(outcome.records).toHaveLength(1);
  expect(outcome.truncated).toBe(false);
});

test("a nextCursor means the page is truncated and must say so", () => {
  const outcome = outcomeFor(pageOf([RECORD], "cursor-abc"));

  expect(outcome.kind === "loaded" && outcome.truncated).toBe(true);
});

test("record counts read naturally at one and at many", () => {
  expect(recordCountLabel(1)).toBe("1 record");
  expect(recordCountLabel(3)).toBe("3 records");
  expect(recordCountLabel(0)).toBe("0 records");
});

// -- the absent patient identity -------------------------------------------------------

test("the listing never claims to know whose record a row is", () => {
  // RecordMetadataResponse carries no patient identifier at all, so there is nothing
  // honest to show; the screens say so rather than leaving a reader to assume a bug.
  const view = toUploadRecordView(RECORD);

  expect(Object.keys(view)).not.toContain("patientHealthId");
  expect(Object.keys(view)).not.toContain("patientId");
  expect(NO_PATIENT_SHOWN).toContain("does not return the patient's identity");
});

// -- the detail mapping, shared with the doctor portal --------------------------------------

test("the detail view exposes every field the endpoint legitimately returns", () => {
  const view = toRecordDetailView(RECORD);

  expect(view).toMatchObject({
    fileName: "cbc-report.pdf",
    categoryCode: "CBC",
    categoryName: "Complete Blood Count",
    description: "Routine pre-operative panel",
    origin: "Hospital upload",
    hospital: "Tata Main Hospital",
    fileType: "PDF",
    processingLabel: "Stored",
  });
  expect(view.fileSize).toMatch(/MB|KB|bytes/);
});
