import { expect, test } from "vitest";

import { formatInstantDate } from "@pulseos/ui";

import { MAX_CATEGORIES_PER_REQUEST, MAX_PURPOSE_LENGTH, type SentAccessRequest } from "./api";
import {
  bucketOf,
  categoryNames,
  draftProblem,
  groupSentRequests,
  daysUntil,
  expiresIn,
  isOpen,
  requestedAgo,
  statusLabel,
  statusTone,
  NO_CATEGORIES_SELECTED,
  REQUEST_SECTIONS,
  purposeProblem,
  purposeRemaining,
  PURPOSE_REQUIRED,
  PURPOSE_TOO_LONG,
  selectionProblem,
  TOO_MANY_CATEGORIES,
  toSentRequestView,
  toSentRequestViews,
  UNKNOWN_HOSPITAL,
} from "./view";

const NOW = Date.parse("2026-09-10T12:00:00Z");
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function iso(offsetMs: number): string {
  return new Date(NOW + offsetMs).toISOString();
}

const LABELS = new Map([
  ["CBC", "Complete Blood Count"],
  ["MRI", "MRI Scan"],
]);

const REQUEST: SentAccessRequest = {
  id: "req-1",
  patientHealthId: "PHI-IND-2026-1QE8DVR",
  status: "PENDING",
  purpose: "Cardiology consultation",
  categoryCodes: ["CBC", "MRI"],
  requesterDoctorId: "doc-1",
  requesterHospitalId: "hos-1",
  expiresAt: iso(6 * DAY),
  createdAt: iso(-2 * HOUR),
  requester: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
  requesterHospitalName: "Apollo Hospitals",
};

function withRequest(overrides: Partial<SentAccessRequest>): SentAccessRequest {
  return { ...REQUEST, ...overrides };
}

// -- status → label ------------------------------------------------------------------------

test("every request status has its own label", () => {
  expect(statusLabel("PENDING")).toBe("Awaiting patient");
  expect(statusLabel("DECIDED")).toBe("Answered");
  expect(statusLabel("EXPIRED")).toBe("Expired");
  expect(statusLabel("CANCELLED")).toBe("Withdrawn");
});

test("a decided request is never called approved — the API does not say which way", () => {
  expect(statusLabel("DECIDED")).not.toMatch(/approv|grant|reject|declin/i);
});

// -- status → tone -------------------------------------------------------------------------

test("only a live request is coloured; closed ones are neutral", () => {
  expect(statusTone("PENDING")).toBe("warning");
  expect(statusTone("DECIDED")).toBe("info");
  expect(statusTone("EXPIRED")).toBe("neutral");
  expect(statusTone("CANCELLED")).toBe("neutral");
});

test("only PENDING counts as open", () => {
  expect(isOpen("PENDING")).toBe(true);
  expect(isOpen("DECIDED")).toBe(false);
  expect(isOpen("EXPIRED")).toBe(false);
  expect(isOpen("CANCELLED")).toBe(false);
});

// -- relative "requested X ago" --------------------------------------------------------------

test("recency reads as prose", () => {
  expect(requestedAgo(iso(-2 * HOUR), NOW)).toBe("requested 2 hours ago");
  expect(requestedAgo(iso(-DAY), NOW)).toBe("requested yesterday");
  expect(requestedAgo(iso(-30 * 1000), NOW)).toBe("requested 30 seconds ago");
});

test("an unparseable timestamp is shown verbatim rather than as Invalid Date", () => {
  expect(requestedAgo("not-a-date", NOW)).toBe("requested not-a-date");
});

// -- "expires in X days" ----------------------------------------------------------------------

test("days remaining round up, so a request lapsing tonight still has a day", () => {
  expect(daysUntil(iso(6 * DAY), NOW)).toBe(6);
  expect(daysUntil(iso(6 * HOUR), NOW)).toBe(1);
  expect(daysUntil(iso(-DAY), NOW)).toBe(-1);
  expect(daysUntil("not-a-date", NOW)).toBeNull();
});

test("the expiry line covers every distance", () => {
  expect(expiresIn(iso(6 * DAY), NOW)).toBe("expires in 6 days");
  expect(expiresIn(iso(2 * DAY), NOW)).toBe("expires in 2 days");
  expect(expiresIn(iso(6 * HOUR), NOW)).toBe("expires tomorrow");
  expect(expiresIn(iso(-HOUR), NOW)).toBe("expired");
  expect(expiresIn(iso(-10 * DAY), NOW)).toBe("expired");
});

test("an unparseable expiry is shown verbatim", () => {
  expect(expiresIn("not-a-date", NOW)).toBe("not-a-date");
});

// -- category code → display name --------------------------------------------------------------

test("codes render as the shared vocabulary's display names, in order", () => {
  expect(categoryNames(["MRI", "CBC"], LABELS)).toEqual(["MRI Scan", "Complete Blood Count"]);
});

test("a code this build has never seen renders as itself", () => {
  expect(categoryNames(["GENOME"], LABELS)).toEqual(["GENOME"]);
});

test("an empty selection maps to an empty list", () => {
  expect(categoryNames([], LABELS)).toEqual([]);
});

// -- the composed view model ---------------------------------------------------------------------

test("a pending request maps to every field the screen needs", () => {
  const view = toSentRequestView(REQUEST, LABELS, NOW);

  expect(view).toMatchObject({
    id: "req-1",
    patientHealthId: "PHI-IND-2026-1QE8DVR",
    hospital: "Apollo Hospitals",
    purpose: "Cardiology consultation",
    categories: ["Complete Blood Count", "MRI Scan"],
    categoryCodes: ["CBC", "MRI"],
    status: "PENDING",
    statusLabel: "Awaiting patient",
    statusTone: "warning",
    requestedAgo: "requested 2 hours ago",
    expiresIn: "expires in 6 days",
  });
  expect(view.requestedOn).toBe(formatInstantDate(REQUEST.createdAt));
});

test("a closed request shows no expiry, where it would mean nothing", () => {
  expect(toSentRequestView(withRequest({ status: "DECIDED" }), LABELS, NOW).expiresIn).toBeNull();
  expect(toSentRequestView(withRequest({ status: "EXPIRED" }), LABELS, NOW).expiresIn).toBeNull();
  expect(toSentRequestView(withRequest({ status: "CANCELLED" }), LABELS, NOW).expiresIn).toBeNull();
});

test("the hospital falls back from the request's own to the requester's, then to a statement", () => {
  expect(toSentRequestView(REQUEST, LABELS, NOW).hospital).toBe("Apollo Hospitals");
  expect(
    toSentRequestView(withRequest({ requesterHospitalName: null }), LABELS, NOW).hospital,
  ).toBe("Apollo");
  expect(
    toSentRequestView(withRequest({ requesterHospitalName: null, requester: null }), LABELS, NOW)
      .hospital,
  ).toBe(UNKNOWN_HOSPITAL);
});

test("mapping a page preserves the API's order", () => {
  const views = toSentRequestViews(
    [REQUEST, withRequest({ id: "req-2", status: "EXPIRED" })],
    LABELS,
    NOW,
  );

  expect(views.map((view) => view.id)).toEqual(["req-1", "req-2"]);
  expect(views.map((view) => view.statusLabel)).toEqual(["Awaiting patient", "Expired"]);
});

test("an empty page maps to an empty list", () => {
  expect(toSentRequestViews([], LABELS, NOW)).toEqual([]);
});

// -- drafting a request -----------------------------------------------------------------------

test("a purpose is required, and blank whitespace does not count as one", () => {
  expect(purposeProblem("")).toBe(PURPOSE_REQUIRED);
  expect(purposeProblem("   \n  ")).toBe(PURPOSE_REQUIRED);
  expect(purposeProblem("Cardiology consultation")).toBeNull();
});

test("a purpose is measured trimmed, against the API's own limit", () => {
  expect(purposeProblem("x".repeat(MAX_PURPOSE_LENGTH))).toBeNull();
  expect(purposeProblem(`  ${"x".repeat(MAX_PURPOSE_LENGTH)}  `)).toBeNull();
  expect(purposeProblem("x".repeat(MAX_PURPOSE_LENGTH + 1))).toBe(PURPOSE_TOO_LONG);
});

test("the remaining-characters counter tracks the trimmed length", () => {
  expect(purposeRemaining("")).toBe(MAX_PURPOSE_LENGTH);
  expect(purposeRemaining("  abc  ")).toBe(MAX_PURPOSE_LENGTH - 3);
  expect(purposeRemaining("x".repeat(MAX_PURPOSE_LENGTH + 5))).toBe(-5);
});

test("a selection needs at least one category and at most the API's maximum", () => {
  expect(selectionProblem([])).toBe(NO_CATEGORIES_SELECTED);
  expect(selectionProblem(["CBC"])).toBeNull();
  expect(
    selectionProblem(Array.from({ length: MAX_CATEGORIES_PER_REQUEST }, (_, i) => `C${i}`)),
  ).toBeNull();
  expect(
    selectionProblem(Array.from({ length: MAX_CATEGORIES_PER_REQUEST + 1 }, (_, i) => `C${i}`)),
  ).toBe(TOO_MANY_CATEGORIES);
});

test("the draft reports the selection problem before the purpose problem", () => {
  expect(draftProblem([], "")).toBe(NO_CATEGORIES_SELECTED);
  expect(draftProblem(["CBC"], "")).toBe(PURPOSE_REQUIRED);
  expect(draftProblem(["CBC"], "Cardiology consultation")).toBeNull();
});

// -- grouping the listing ----------------------------------------------------------------------

test("each status files under its own section", () => {
  expect(bucketOf("PENDING")).toBe("pending");
  expect(bucketOf("DECIDED")).toBe("answered");
  expect(bucketOf("EXPIRED")).toBe("expired");
  expect(bucketOf("CANCELLED")).toBe("withdrawn");
});

test("the sections are ordered waiting-first, and each heading matches its badge", () => {
  expect(REQUEST_SECTIONS.map((section) => section.bucket)).toEqual([
    "pending",
    "answered",
    "expired",
    "withdrawn",
  ]);
  // Headings come from statusLabel, so a section can never disagree with the cards in it.
  expect(REQUEST_SECTIONS.map((section) => statusLabel(section.status))).toEqual([
    "Awaiting patient",
    "Answered",
    "Expired",
    "Withdrawn",
  ]);
});

test("grouping files every request and preserves the API's order within a section", () => {
  const requests = [
    withRequest({ id: "a", status: "PENDING" }),
    withRequest({ id: "b", status: "DECIDED" }),
    withRequest({ id: "c", status: "PENDING" }),
    withRequest({ id: "d", status: "EXPIRED" }),
    withRequest({ id: "e", status: "CANCELLED" }),
  ];

  const buckets = groupSentRequests(toSentRequestViews(requests, LABELS, NOW));

  expect(buckets.pending.map((view) => view.id)).toEqual(["a", "c"]);
  expect(buckets.answered.map((view) => view.id)).toEqual(["b"]);
  expect(buckets.expired.map((view) => view.id)).toEqual(["d"]);
  expect(buckets.withdrawn.map((view) => view.id)).toEqual(["e"]);
});

test("an empty listing groups to four empty sections, not to null", () => {
  const buckets = groupSentRequests([]);

  expect(buckets).toEqual({ pending: [], answered: [], expired: [], withdrawn: [] });
});

test("grouping never re-derives a status from a date — the server is the authority", () => {
  // PENDING past its deadline (no expiry sweep runs server-side): it stays in "Awaiting
  // patient" because that is what the API reported, and the card says "expired" beside it.
  const stale = withRequest({ status: "PENDING", expiresAt: iso(-DAY) });

  const buckets = groupSentRequests(toSentRequestViews([stale], LABELS, NOW));

  expect(buckets.pending).toHaveLength(1);
  expect(buckets.expired).toEqual([]);
  expect(buckets.pending[0]?.expiresIn).toBe("expired");
});
