import { expect, test } from "vitest";

import { formatCalendarDate, formatFileSize, formatInstantDate } from "@pulseos/ui";

import type { RecordMetadata } from "./api";
import {
  descriptionOf,
  fileTypeLabel,
  hospitalLabel,
  originLabel,
  PATIENT_UPLOADED,
  POPUP_BLOCKED,
  processingLabel,
  processingTone,
  toRecordDetailView,
  UNKNOWN_HOSPITAL,
} from "./view";

const RECORD: RecordMetadata = {
  id: "rec-1",
  categoryCode: "CBC",
  categoryDisplayName: "Complete Blood Count",
  origin: "HOSPITAL_UPLOAD",
  dateOfService: "2026-03-01",
  description: "Routine pre-operative panel",
  originalFilename: "cbc report.pdf",
  contentType: "application/pdf",
  sizeBytes: 2_516_582,
  processingStatus: "UPLOADED",
  isHidden: false,
  uploadedByHospital: { hid: "HID-0001", name: "TMH Jamshedpur" },
  createdAt: "2026-09-04T10:00:00Z",
};

// -- metadata mapping ------------------------------------------------------------------------

test("a record maps to exactly the facts the endpoint exposes", () => {
  expect(toRecordDetailView(RECORD)).toEqual({
    fileName: "cbc report.pdf",
    categoryCode: "CBC",
    categoryName: "Complete Blood Count",
    dateOfService: formatCalendarDate("2026-03-01"),
    description: "Routine pre-operative panel",
    origin: "Hospital upload",
    hospital: "TMH Jamshedpur",
    uploadedOn: formatInstantDate("2026-09-04T10:00:00Z"),
    fileSize: formatFileSize(2_516_582),
    fileType: "PDF",
    processingLabel: "Stored",
    processingTone: "neutral",
  });
});

test("nothing is invented: a null description stays null so the row can be omitted", () => {
  expect(descriptionOf({ ...RECORD, description: null })).toBeNull();
  expect(descriptionOf({ ...RECORD, description: "   " })).toBeNull();
  expect(toRecordDetailView({ ...RECORD, description: null }).description).toBeNull();
});

test("a description is trimmed but never reworded", () => {
  expect(descriptionOf({ ...RECORD, description: "  Follow-up panel  " })).toBe("Follow-up panel");
});

test("a service date is a calendar date and an upload is an instant — not the same format", () => {
  const view = toRecordDetailView(RECORD);

  // Formatted in UTC, so it cannot slip a day for a reader west of Greenwich.
  expect(view.dateOfService).toBe(formatCalendarDate("2026-03-01"));
  expect(view.uploadedOn).toBe(formatInstantDate("2026-09-04T10:00:00Z"));
});

// -- origin and hospital -----------------------------------------------------------------------

test("origin reads as a trust signal, not an enum", () => {
  expect(originLabel("HOSPITAL_UPLOAD")).toBe("Hospital upload");
  expect(originLabel("PATIENT_LOCKER")).toBe("Patient locker");
});

test("a locker record names who added it; an unresolvable hospital is never left blank", () => {
  expect(hospitalLabel(null, "PATIENT_LOCKER")).toBe(PATIENT_UPLOADED);
  expect(hospitalLabel(null, "HOSPITAL_UPLOAD")).toBe(UNKNOWN_HOSPITAL);
  expect(
    toRecordDetailView({ ...RECORD, origin: "PATIENT_LOCKER", uploadedByHospital: null }).hospital,
  ).toBe(PATIENT_UPLOADED);
});

// -- file size and type -------------------------------------------------------------------------

test("file sizes read in the unit a person would use", () => {
  expect(formatFileSize(0)).toBe("0 B");
  expect(formatFileSize(512)).toBe("512 B");
  expect(formatFileSize(1024)).toBe("1 KB");
  expect(formatFileSize(1536)).toBe("2 KB");
  expect(formatFileSize(1024 * 1024)).toBe("1.0 MB");
  expect(formatFileSize(2_516_582)).toBe("2.4 MB");
});

test("the three accepted formats are named, and anything else is shown verbatim", () => {
  expect(fileTypeLabel("application/pdf")).toBe("PDF");
  expect(fileTypeLabel("image/jpeg")).toBe("JPEG image");
  expect(fileTypeLabel("image/png")).toBe("PNG image");
  // A guess would be worse than the truth.
  expect(fileTypeLabel("application/dicom")).toBe("application/dicom");
});

// -- processing status ----------------------------------------------------------------------------

test("every pipeline state has wording and a tone, and none implies an unbuilt capability", () => {
  expect(processingLabel("UPLOADED")).toBe("Stored");
  expect(processingLabel("PROCESSING")).toBe("Being processed");
  expect(processingLabel("INDEXED")).toBe("Indexed");
  expect(processingLabel("FAILED")).toBe("Processing failed");

  expect(processingTone("UPLOADED")).toBe("neutral");
  expect(processingTone("PROCESSING")).toBe("info");
  expect(processingTone("INDEXED")).toBe("success");
  expect(processingTone("FAILED")).toBe("destructive");
});

test("the blocked-popup message does not claim nothing happened", () => {
  // By then the server has issued the link and audited the download.
  expect(POPUP_BLOCKED).toContain("blocked");
  expect(POPUP_BLOCKED).not.toContain("Nothing");
});
