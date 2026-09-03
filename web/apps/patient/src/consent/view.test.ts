import { expect, test } from "vitest";

import { formatInstantDate } from "@/lib/dates";

import type { AccessRequest, DecisionOutcome } from "./api";
import {
  bucketFor,
  clinicianLine,
  groupRequests,
  hospitalLine,
  recordedOutcome,
  toRequestView,
  UNKNOWN_CLINICIAN,
  UNKNOWN_HOSPITAL,
  type RecordedOutcome,
} from "./view";

const NOW = Date.parse("2026-09-03T12:00:00Z");

const REQUEST: AccessRequest = {
  id: "req-1",
  status: "PENDING",
  purpose: "Cardiology consultation",
  categoryCodes: ["CBC", "LAB_REPORT"],
  requesterDoctorId: "doc-1",
  requesterHospitalId: "hos-1",
  expiresAt: "2026-09-10T12:00:00Z",
  createdAt: "2026-09-03T10:00:00Z",
  requester: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
  requesterHospitalName: "Apollo Hospitals",
};

const LABELS = new Map([
  ["CBC", "Complete Blood Count"],
  ["LAB_REPORT", "Lab Report"],
]);

const NONE: ReadonlyMap<string, RecordedOutcome> = new Map();

function withRequest(overrides: Partial<AccessRequest>): AccessRequest {
  return { ...REQUEST, ...overrides };
}

test("the clinician line carries the specialty only when the record has one", () => {
  expect(clinicianLine(REQUEST)).toBe("Dr Meera Sharma · Cardiology");
  expect(
    clinicianLine(
      withRequest({ requester: { fullName: "Dr Rao", specialty: null, hospitalName: "TMH" } }),
    ),
  ).toBe("Dr Rao");
});

test("an unresolved requester is stated, not invented", () => {
  const anonymous = withRequest({ requester: null, requesterHospitalName: null });

  expect(clinicianLine(anonymous)).toBe(UNKNOWN_CLINICIAN);
  expect(hospitalLine(anonymous)).toBe(UNKNOWN_HOSPITAL);
});

test("the hospital shown is the one the request was raised under", () => {
  expect(hospitalLine(REQUEST)).toBe("Apollo Hospitals");
  // Falls back to where the requester practises when the request carries no name.
  expect(hospitalLine(withRequest({ requesterHospitalName: null }))).toBe("Apollo");
});

test("each request status maps to its own section", () => {
  expect(bucketFor(withRequest({ status: "PENDING" }), NONE)).toBe("pending");
  expect(bucketFor(withRequest({ status: "EXPIRED" }), NONE)).toBe("expired");
  expect(bucketFor(withRequest({ status: "CANCELLED" }), NONE)).toBe("withdrawn");
});

test("a request decided before this session is filed as answered, not guessed at", () => {
  expect(bucketFor(withRequest({ status: "DECIDED" }), NONE)).toBe("decided");
});

test("an outcome recorded this session outranks the status the page loaded", () => {
  const outcomes = new Map<string, RecordedOutcome>([["req-1", "approved"]]);

  expect(bucketFor(REQUEST, outcomes)).toBe("approved");
  expect(bucketFor(REQUEST, new Map([["req-1", "rejected"]]))).toBe("rejected");
});

test("categories render as display names and keep their codes for the answer", () => {
  const view = toRequestView(REQUEST, LABELS, NONE, NOW);

  expect(view.categories).toEqual(["Complete Blood Count", "Lab Report"]);
  expect(view.categoryCodes).toEqual(["CBC", "LAB_REPORT"]);
});

test("a category this build has never seen renders as its code", () => {
  const view = toRequestView(withRequest({ categoryCodes: ["GENOME"] }), LABELS, NONE, NOW);

  expect(view.categories).toEqual(["GENOME"]);
});

test("timestamps read as recency and as dates", () => {
  const view = toRequestView(REQUEST, LABELS, NONE, NOW);

  expect(view.requestedAgo).toBe("2 hours ago");
  // Compared against the shared formatter rather than a literal: month abbreviations come
  // from the runtime's locale data, and lib/dates owns that behaviour (and tests it).
  expect(view.requestedOn).toBe(formatInstantDate(REQUEST.createdAt));
  expect(view.expiresOn).toBe(formatInstantDate(REQUEST.expiresAt));
  expect(view.requestedOn).toContain("2026");
});

test("the badge follows the section", () => {
  expect(toRequestView(REQUEST, LABELS, NONE, NOW).statusLabel).toBe("Pending");
  const declined = toRequestView(REQUEST, LABELS, new Map([["req-1", "rejected"]]), NOW);
  expect(declined.statusLabel).toBe("Declined");
  expect(declined.statusTone).toBe("destructive");
});

test("grouping files every request and preserves the order within a section", () => {
  const requests = [
    withRequest({ id: "a", status: "PENDING" }),
    withRequest({ id: "b", status: "PENDING" }),
    withRequest({ id: "c", status: "EXPIRED" }),
    withRequest({ id: "d", status: "DECIDED" }),
  ];

  const buckets = groupRequests(requests, LABELS, new Map([["d", "approved"]]), NOW);

  expect(buckets.pending.map((view) => view.id)).toEqual(["a", "b"]);
  expect(buckets.expired.map((view) => view.id)).toEqual(["c"]);
  expect(buckets.approved.map((view) => view.id)).toEqual(["d"]);
  expect(buckets.rejected).toEqual([]);
  expect(buckets.decided).toEqual([]);
});

function outcome(overrides: Partial<DecisionOutcome>): DecisionOutcome {
  return {
    requestId: "req-1",
    requestStatus: "DECIDED",
    decisions: [],
    grants: [],
    ...overrides,
  };
}

test("the recorded outcome is read from what the API decided, not from the button", () => {
  const approved = outcome({
    decisions: [
      { id: "d1", categoryCode: "CBC", status: "APPROVED", decidedAt: "2026-09-03T12:00:00Z" },
      {
        id: "d2",
        categoryCode: "LAB_REPORT",
        status: "REJECTED",
        decidedAt: "2026-09-03T12:00:00Z",
      },
    ],
  });
  const rejected = outcome({
    decisions: [
      { id: "d3", categoryCode: "CBC", status: "REJECTED", decidedAt: "2026-09-03T12:00:00Z" },
    ],
  });

  // A partial approval is still an approval: something was granted.
  expect(recordedOutcome(approved)).toBe("approved");
  expect(recordedOutcome(rejected)).toBe("rejected");
});

test("a request left open by an answer records nothing, so the page reloads instead", () => {
  expect(recordedOutcome(outcome({ requestStatus: "PENDING" }))).toBeNull();
});
