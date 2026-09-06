import { expect, test } from "vitest";

import { todayIsoDate } from "@pulseos/ui";

import type { RecordMetadata } from "./api";
import {
  HEALTH_ID_CAUTION,
  INVALID_HEALTH_ID,
  UNKNOWN_HOSPITAL,
  draftProblems,
  emptyDraft,
  fieldProblem,
  isSendable,
  looksLikeHealthId,
  normalizeHealthId,
  toReceiptView,
  type UploadDraft,
} from "./view";

const FILE = new File(["x"], "report.pdf", { type: "application/pdf" });

const VALID: UploadDraft = {
  patientHealthId: "PHI-IND-2026-7K3M99X",
  file: FILE,
  categoryCode: "CBC",
  dateOfService: "2026-07-01",
  description: "",
};

function withDraft(overrides: Partial<UploadDraft>): UploadDraft {
  return { ...VALID, ...overrides };
}

test("a Health ID is normalised the way ADR-012 stores it", () => {
  expect(normalizeHealthId("  phi-ind-2026-7k3m99x  ")).toBe("PHI-IND-2026-7K3M99X");
});

test("the shape check accepts a real ID and rejects a malformed one", () => {
  expect(looksLikeHealthId("phi-ind-2026-7k3m99x")).toBe(true);
  expect(looksLikeHealthId("PHI-IND-2026-7K3M99")).toBe(false);
  expect(looksLikeHealthId("ABC-IND-2026-7K3M99X")).toBe(false);
  expect(looksLikeHealthId("PHI-IND-26-7K3M99X")).toBe(false);
});

test("the shape check does not pretend to verify the check character", () => {
  // ISO 7064 lives in app/modules/patients/health_id.py and is deliberately not copied here.
  // A well-formed ID with the wrong check character passes locally and is the server's 422.
  expect(looksLikeHealthId("PHI-IND-2026-7K3M99A")).toBe(true);
});

test("a complete draft is sendable and reports no problems", () => {
  expect(draftProblems(VALID)).toEqual({});
  expect(isSendable(VALID)).toBe(true);
});

test("an empty draft blocks on everything except the date, which defaults to today", () => {
  const draft = emptyDraft();

  expect(draft.dateOfService).toBe(todayIsoDate());
  expect(Object.keys(draftProblems(draft)).sort()).toEqual([
    "categoryCode",
    "file",
    "patientHealthId",
  ]);
});

test("a malformed Health ID is caught before the round trip", () => {
  expect(fieldProblem("patientHealthId", withDraft({ patientHealthId: "nonsense" }))).toBe(
    INVALID_HEALTH_ID,
  );
  expect(isSendable(withDraft({ patientHealthId: "nonsense" }))).toBe(false);
});

test("a future service date is refused locally, because the API refuses it too", () => {
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

  expect(fieldProblem("dateOfService", withDraft({ dateOfService: tomorrow }))).toContain(
    "cannot be in the future",
  );
  expect(fieldProblem("dateOfService", withDraft({ dateOfService: todayIsoDate() }))).toBeNull();
});

test("the description is optional — it is the only field the API accepts as absent", () => {
  expect(isSendable(withDraft({ description: "" }))).toBe(true);
});

test("the caution says the two things an administrator cannot discover for themselves", () => {
  // There is no patient lookup for a hospital admin, and no endpoint edits or deletes a
  // record, so a wrong Health ID is unrecoverable from this portal.
  expect(HEALTH_ID_CAUTION).toContain("cannot be edited or removed");
  expect(HEALTH_ID_CAUTION).toContain("Read it back");
});

test("the receipt names the patient the document was filed against", () => {
  const record = {
    id: "rec-1",
    categoryDisplayName: "Complete Blood Count",
    dateOfService: "2026-07-01",
    originalFilename: "cbc.pdf",
    sizeBytes: 2048,
    uploadedByHospital: { hid: "HID-0001", name: "Tata Main Hospital" },
  } as RecordMetadata;

  const view = toReceiptView(
    record,
    "PHI-IND-2026-7K3M99X",
    () => "1 Jul 2026",
    () => "2 KB",
  );

  expect(view.patientHealthId).toBe("PHI-IND-2026-7K3M99X");
  expect(view.recordId).toBe("rec-1");
  expect(view.category).toBe("Complete Blood Count");
  expect(view.uploadedTo).toBe("Tata Main Hospital");
});

test("a receipt without an uploading hospital still names somewhere truthful", () => {
  const record = {
    id: "rec-2",
    categoryDisplayName: "X-Ray",
    dateOfService: "2026-07-01",
    originalFilename: "x.pdf",
    sizeBytes: 1,
    uploadedByHospital: null,
  } as RecordMetadata;

  expect(
    toReceiptView(
      record,
      "PHI-IND-2026-7K3M99X",
      () => "",
      () => "",
    ).uploadedTo,
  ).toBe(UNKNOWN_HOSPITAL);
});
