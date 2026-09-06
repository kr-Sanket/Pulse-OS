import { expect, test } from "vitest";

import { todayIsoDate } from "@pulseos/ui";

import type { PatientIdentity } from "@/patient-lookup/view";

import type { RecordMetadata } from "./api";
import {
  CATEGORIES_BLOCKED,
  DRAFT_INCOMPLETE,
  PATIENT_NOT_CONFIRMED,
  PENDING_HOSPITAL_BLOCKED,
  UNKNOWN_HOSPITAL,
  canUpload,
  draftProblems,
  emptyDraft,
  fieldProblem,
  isSendable,
  toReceiptView,
  uploadBlockedReason,
  type UploadDraft,
  type UploadGate,
} from "./view";

const FILE = new File(["x"], "report.pdf", { type: "application/pdf" });

const VALID: UploadDraft = {
  file: FILE,
  categoryCode: "CBC",
  dateOfService: "2026-07-01",
  description: "",
};

const PATIENT: PatientIdentity = {
  healthId: "PHI-IND-2026-7K3M99X",
  fullName: "Asha Rao",
};

function withDraft(overrides: Partial<UploadDraft>): UploadDraft {
  return { ...VALID, ...overrides };
}

function gateWith(overrides: Partial<UploadGate> = {}): UploadGate {
  return {
    hospitalCanOperate: true,
    categoriesAvailable: true,
    patientConfirmed: true,
    draft: VALID,
    ...overrides,
  };
}

// -- the document draft ------------------------------------------------------------------

test("a complete draft is sendable and reports no problems", () => {
  expect(draftProblems(VALID)).toEqual({});
  expect(isSendable(VALID)).toBe(true);
});

test("the draft no longer carries a Health ID — an upload runs on a confirmed patient", () => {
  // The identifier lives in patient-lookup/, so "typed an ID" and "confirmed a patient"
  // cannot be confused for one another.
  expect(Object.keys(emptyDraft()).sort()).toEqual([
    "categoryCode",
    "dateOfService",
    "description",
    "file",
  ]);
});

test("an empty draft blocks on file and category; the date defaults to today", () => {
  const draft = emptyDraft();

  expect(draft.dateOfService).toBe(todayIsoDate());
  expect(Object.keys(draftProblems(draft)).sort()).toEqual(["categoryCode", "file"]);
});

test("a future service date is refused locally, because the API refuses it too", () => {
  // The bound is a *local* calendar date (todayIsoDate), so the future date here is built
  // from a fixed far-future value rather than from a UTC instant: deriving "tomorrow" by
  // adding 24h to Date.now() and slicing the ISO string compares UTC against local, and
  // silently passes for readers east of Greenwich late in the day.
  expect(fieldProblem("dateOfService", withDraft({ dateOfService: "2099-01-01" }))).toContain(
    "cannot be in the future",
  );
  expect(fieldProblem("dateOfService", withDraft({ dateOfService: todayIsoDate() }))).toBeNull();
});

test("the description is optional — it is the only field the API accepts as absent", () => {
  expect(isSendable(withDraft({ description: "" }))).toBe(true);
});

// -- the upload gate ---------------------------------------------------------------------

test("everything in place means the upload may proceed", () => {
  expect(canUpload(gateWith())).toBe(true);
  expect(uploadBlockedReason(gateWith())).toBeNull();
});

test("upload is blocked until a patient has been confirmed", () => {
  const gate = gateWith({ patientConfirmed: false });

  expect(canUpload(gate)).toBe(false);
  expect(uploadBlockedReason(gate)).toBe(PATIENT_NOT_CONFIRMED);
});

test("a PENDING hospital stays blocked, and is told so first", () => {
  // ADR-015: the API answers 409. The existing canOperate behaviour is unchanged by this
  // slice, and it outranks every other blocker because nothing else can fix it.
  const gate = gateWith({
    hospitalCanOperate: false,
    patientConfirmed: false,
    draft: emptyDraft(),
  });

  expect(canUpload(gate)).toBe(false);
  expect(uploadBlockedReason(gate)).toBe(PENDING_HOSPITAL_BLOCKED);
});

test("a PENDING hospital is blocked even with a confirmed patient and a complete draft", () => {
  expect(canUpload(gateWith({ hospitalCanOperate: false }))).toBe(false);
});

test("a missing category vocabulary blocks the upload", () => {
  const gate = gateWith({ categoriesAvailable: false });

  expect(uploadBlockedReason(gate)).toBe(CATEGORIES_BLOCKED);
});

test("a confirmed patient with an incomplete document is blocked on the document", () => {
  const gate = gateWith({ draft: emptyDraft() });

  expect(canUpload(gate)).toBe(false);
  expect(uploadBlockedReason(gate)).toBe(DRAFT_INCOMPLETE);
});

test("the first blocker wins, so the operator is told one thing to do next", () => {
  const everythingWrong: UploadGate = {
    hospitalCanOperate: false,
    categoriesAvailable: false,
    patientConfirmed: false,
    draft: emptyDraft(),
  };

  expect(uploadBlockedReason(everythingWrong)).toBe(PENDING_HOSPITAL_BLOCKED);
});

// -- the receipt -------------------------------------------------------------------------

const RECORD = {
  id: "rec-1",
  categoryDisplayName: "Complete Blood Count",
  dateOfService: "2026-07-01",
  originalFilename: "cbc.pdf",
  sizeBytes: 2048,
  uploadedByHospital: { hid: "HID-0001", name: "Tata Main Hospital" },
} as RecordMetadata;

test("the receipt names the confirmed patient, not just the Health ID", () => {
  // The whole point of the slice: an operator must be able to see who they filed for.
  const view = toReceiptView(
    RECORD,
    PATIENT,
    () => "1 Jul 2026",
    () => "2 KB",
  );

  expect(view.patientName).toBe("Asha Rao");
  expect(view.patientHealthId).toBe("PHI-IND-2026-7K3M99X");
  expect(view.recordId).toBe("rec-1");
  expect(view.uploadedTo).toBe("Tata Main Hospital");
});

test("the receipt's patient comes from the lookup, never from the upload response", () => {
  // POST /records returns no patient at all; it was deliberately not widened to add one.
  expect(Object.keys(RECORD)).not.toContain("patientHealthId");
});

test("a receipt without an uploading hospital still names somewhere truthful", () => {
  const locker = { ...RECORD, uploadedByHospital: null } as RecordMetadata;

  expect(
    toReceiptView(
      locker,
      PATIENT,
      () => "",
      () => "",
    ).uploadedTo,
  ).toBe(UNKNOWN_HOSPITAL);
});
