import { expect, test } from "vitest";

import { formatCalendarDate, formatInstantDate } from "@pulseos/ui";

import type { GrantedRecord, GrantedRecordPage } from "./api";
import {
  grantedCategoryNames,
  hasGrant,
  hospitalLabel,
  joinCategories,
  originLabel,
  outcomeFor,
  PATIENT_UPLOADED,
  recordCountLabel,
  toGrantedRecordView,
  toGrantedRecordViews,
  UNKNOWN_HOSPITAL,
} from "./view";

const HOSPITAL_RECORD: GrantedRecord = {
  id: "rec-1",
  categoryCode: "CBC",
  categoryDisplayName: "Complete Blood Count",
  origin: "HOSPITAL_UPLOAD",
  dateOfService: "2026-03-01",
  uploadedByHospital: { hid: "HID-0001", name: "TMH Jamshedpur" },
  createdAt: "2026-09-04T10:00:00Z",
};

const LOCKER_RECORD: GrantedRecord = {
  ...HOSPITAL_RECORD,
  id: "rec-2",
  origin: "PATIENT_LOCKER",
  uploadedByHospital: null,
};

const CBC = { code: "CBC", displayName: "Complete Blood Count" };
const MRI = { code: "MRI", displayName: "MRI Scan" };

const PATIENT_ID = "00000000-0000-0000-0000-000000000001";

function page(overrides: Partial<GrantedRecordPage> = {}): GrantedRecordPage {
  return { patientId: PATIENT_ID, grantedCategories: [], items: [], nextCursor: null, ...overrides };
}

// -- view mapping -------------------------------------------------------------------------

test("a record maps to exactly the six facts a clinician chooses with", () => {
  const view = toGrantedRecordView(HOSPITAL_RECORD);

  expect(view).toEqual({
    id: "rec-1",
    categoryCode: "CBC",
    categoryName: "Complete Blood Count",
    dateOfService: formatCalendarDate("2026-03-01"),
    origin: "Hospital upload",
    hospital: "TMH Jamshedpur",
    addedOn: formatInstantDate("2026-09-04T10:00:00Z"),
  });
});

test("the view carries an id for keying and nothing that describes the document", () => {
  const keys = Object.keys(toGrantedRecordView(HOSPITAL_RECORD)).sort();

  expect(keys).toEqual([
    "addedOn",
    "categoryCode",
    "categoryName",
    "dateOfService",
    "hospital",
    "id",
    "origin",
  ]);
  // The response does not carry these at all; the view must never grow them either.
  expect(keys).not.toContain("originalFilename");
  expect(keys).not.toContain("description");
  expect(keys).not.toContain("sizeBytes");
  expect(keys).not.toContain("contentType");
  expect(keys).not.toContain("processingStatus");
});

test("a page maps in the order the API returned it, and is never re-sorted", () => {
  const older: GrantedRecord = { ...HOSPITAL_RECORD, id: "rec-0", dateOfService: "2020-01-01" };
  // Newest-added first, with the oldest *service* date at the top: re-sorting a page that
  // may be truncated would imply an old record was the most recent thing about this patient.
  const views = toGrantedRecordViews([older, HOSPITAL_RECORD]);

  expect(views.map((view) => view.id)).toEqual(["rec-0", "rec-1"]);
});

// -- origin and hospital labels -------------------------------------------------------------

test("origin reads as a trust signal, not an enum", () => {
  expect(originLabel("HOSPITAL_UPLOAD")).toBe("Hospital upload");
  expect(originLabel("PATIENT_LOCKER")).toBe("Patient locker");
});

test("a locker record says who added it rather than showing a dash", () => {
  expect(toGrantedRecordView(LOCKER_RECORD).hospital).toBe(PATIENT_UPLOADED);
  expect(hospitalLabel(null, "PATIENT_LOCKER")).toBe(PATIENT_UPLOADED);
});

test("a hospital upload whose hospital no longer resolves is never left blank", () => {
  expect(hospitalLabel(null, "HOSPITAL_UPLOAD")).toBe(UNKNOWN_HOSPITAL);
});

// -- date formatting ------------------------------------------------------------------------

test("a service date is a calendar date and an upload is an instant — not the same format", () => {
  const view = toGrantedRecordView({
    ...HOSPITAL_RECORD,
    dateOfService: "2026-03-01",
    createdAt: "2026-09-04T10:00:00Z",
  });

  // Formatted in UTC, so it cannot slip a day for a reader west of Greenwich.
  expect(view.dateOfService).toBe(formatCalendarDate("2026-03-01"));
  expect(view.addedOn).toBe(formatInstantDate("2026-09-04T10:00:00Z"));
});

test("an unparseable timestamp is shown verbatim rather than as Invalid Date", () => {
  const view = toGrantedRecordView({ ...HOSPITAL_RECORD, dateOfService: "not-a-date" });

  expect(view.dateOfService).toBe("not-a-date");
});

// -- empty-state derivation ------------------------------------------------------------------

test("no granted category is 'no grant', whatever the items say", () => {
  expect(outcomeFor(page())).toEqual({ kind: "no-grant" });
  expect(hasGrant(page())).toBe(false);
});

test("a live grant over an empty patient is a different answer from no grant", () => {
  const outcome = outcomeFor(page({ grantedCategories: [CBC] }));

  expect(outcome).toEqual({
    kind: "granted-empty",
    categories: ["Complete Blood Count"],
    patientId: PATIENT_ID,
  });
  expect(outcome.kind).not.toBe("no-grant");
  expect(hasGrant(page({ grantedCategories: [CBC] }))).toBe(true);
});

test("records under a grant load, and the scope is reported beside them", () => {
  const outcome = outcomeFor(
    page({ grantedCategories: [CBC, MRI], items: [HOSPITAL_RECORD, LOCKER_RECORD] }),
  );

  expect(outcome.kind).toBe("loaded");
  if (outcome.kind !== "loaded") {
    return;
  }
  expect(outcome.records.map((record) => record.id)).toEqual(["rec-1", "rec-2"]);
  expect(outcome.categories).toEqual(["Complete Blood Count", "MRI Scan"]);
  expect(outcome.truncated).toBe(false);
  expect(outcome.patientId).toBe(PATIENT_ID);
});

test("a full page admits that there is more rather than implying it is everything", () => {
  const outcome = outcomeFor(
    page({ grantedCategories: [CBC], items: [HOSPITAL_RECORD], nextCursor: "next" }),
  );

  expect(outcome).toMatchObject({ kind: "loaded", truncated: true });
});

test("category names keep the vocabulary order the API sent", () => {
  expect(grantedCategoryNames([CBC, MRI])).toEqual(["Complete Blood Count", "MRI Scan"]);
  expect(grantedCategoryNames([])).toEqual([]);
});

// -- wording ---------------------------------------------------------------------------------

test("counts and lists read as sentences", () => {
  expect(recordCountLabel(1)).toBe("1 record");
  expect(recordCountLabel(0)).toBe("0 records");
  expect(recordCountLabel(3)).toBe("3 records");

  expect(joinCategories([])).toBe("");
  expect(joinCategories(["CBC"])).toBe("CBC");
  expect(joinCategories(["CBC", "MRI"])).toBe("CBC and MRI");
  expect(joinCategories(["CBC", "MRI", "X-Ray"])).toBe("CBC, MRI and X-Ray");
});
