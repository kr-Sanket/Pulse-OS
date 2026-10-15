import { expect, test } from "vitest";

import { formatInstantDate, formatInstantTime } from "@pulseos/ui";

import type { HospitalAuditEvent, HospitalAuditPage } from "./api";
import {
  EMPTY_BODY,
  EMPTY_TITLE,
  PAGE_DESCRIPTION,
  SCOPE_NOTE,
  UNKNOWN_ACTION_LABEL,
  actionLabel,
  actionTone,
  actorName,
  appendPage,
  hasMorePages,
  recordReference,
  roleLabel,
  toAuditEventView,
  toAuditEventViews,
} from "./view";

const EVENT: HospitalAuditEvent = {
  id: "evt-1",
  action: "RECORD_VIEWED",
  actorUserId: "11111111-1111-4111-8111-111111111111",
  actorRole: "HOSPITAL_ADMIN",
  actor: { fullName: "Anita Rao", specialty: null, hospitalName: "TMH Jamshedpur" },
  targetRecordId: "abcdef12-3456-4789-8abc-def123456789",
  occurredAt: "2026-09-04T09:30:00Z",
};

function withEvent(overrides: Partial<HospitalAuditEvent>): HospitalAuditEvent {
  return { ...EVENT, ...overrides };
}

// -- action labels -------------------------------------------------------------------

test("the four hospital actions read as sentences, not as codes", () => {
  expect(actionLabel("RECORD_UPLOADED")).toBe("Record uploaded");
  expect(actionLabel("RECORD_VIEWED")).toBe("Record viewed");
  expect(actionLabel("RECORD_DOWNLOADED")).toBe("Record downloaded");
  expect(actionLabel("ACCESS_DENIED")).toBe("Access denied");
});

test("a clinician's AI search is labelled apart from a listing", () => {
  expect(actionLabel("RECORDS_SEARCHED")).toBe("Records searched (AI)");
  expect(actionLabel("RECORDS_SEARCHED")).not.toBe(actionLabel("RECORDS_LISTED"));
  expect(actionTone("RECORDS_SEARCHED")).toBe("info");
});

test("a refusal is toned apart from a routine read", () => {
  expect(actionTone("ACCESS_DENIED")).toBe("destructive");
  expect(actionTone("RECORD_VIEWED")).toBe("info");
  expect(actionTone("RECORD_UPLOADED")).toBe("neutral");
});

test("an unknown action falls back safely and never shows its raw code", () => {
  // An action added server-side after this build shipped. The row is still rendered —
  // dropping an audit entry is not an option — but nothing guesses at its meaning.
  expect(actionLabel("SOMETHING_ADDED_LATER")).toBe(UNKNOWN_ACTION_LABEL);
  expect(actionLabel("SOMETHING_ADDED_LATER")).not.toContain("SOMETHING");
  expect(actionTone("SOMETHING_ADDED_LATER")).toBe("neutral");
});

// -- role labels ---------------------------------------------------------------------

test("roles are human-readable", () => {
  expect(roleLabel("HOSPITAL_ADMIN")).toBe("Hospital administrator");
  expect(roleLabel("DOCTOR")).toBe("Doctor");
  expect(roleLabel("PATIENT")).toBe("Patient");
  expect(roleLabel("SYSTEM_ADMIN")).toBe("PulseOS administrator");
});

test("an unrecognised role does not crash or leak its code", () => {
  expect(roleLabel("WHATEVER")).toBe("Unknown role");
});

// -- actor identity --------------------------------------------------------------------

test("the actor is named when the projection resolved a name", () => {
  expect(actorName(EVENT)).toBe("Anita Rao");
});

test("an unnamed actor falls back to their role, never to a user id", () => {
  const anonymous = withEvent({ actor: null });

  expect(actorName(anonymous)).toBe("Hospital administrator");
  expect(actorName(anonymous)).not.toContain(EVENT.actorUserId);
});

test("a blank name is treated as no name", () => {
  const blank = withEvent({
    actor: { fullName: "   ", specialty: null, hospitalName: "TMH Jamshedpur" },
  });

  expect(actorName(blank)).toBe("Hospital administrator");
});

// -- record reference --------------------------------------------------------------------

test("a record target becomes a compact handle, never a description", () => {
  expect(recordReference(EVENT.targetRecordId)).toBe("abcdef12");
});

test("no record target means no reference at all, not a placeholder", () => {
  expect(recordReference(null)).toBeNull();
  expect(recordReference("")).toBeNull();
  expect(toAuditEventView(withEvent({ targetRecordId: null })).record).toBeNull();
});

// -- the display model ---------------------------------------------------------------------

test("an event maps to exactly what the card renders", () => {
  const view = toAuditEventView(EVENT);

  expect(view).toEqual({
    id: "evt-1",
    actionLabel: "Record viewed",
    actionTone: "info",
    actor: "Anita Rao",
    role: "Hospital administrator",
    date: formatInstantDate("2026-09-04T09:30:00Z"),
    time: formatInstantTime("2026-09-04T09:30:00Z"),
    record: "abcdef12",
  });
});

test("the role is dropped when it is already standing in as the name", () => {
  // Otherwise the card would read "Hospital administrator · Hospital administrator".
  expect(toAuditEventView(withEvent({ actor: null })).role).toBeNull();
});

test("the view model exposes nothing the endpoint withholds", () => {
  const view = toAuditEventView(EVENT);

  expect(Object.keys(view).sort()).toEqual([
    "actionLabel",
    "actionTone",
    "actor",
    "date",
    "id",
    "record",
    "role",
    "time",
  ]);
  // No patient, no hospital, no digest — and no raw actor id reaching the UI.
  expect(Object.values(view).join(" ")).not.toContain(EVENT.actorUserId);
});

test("the server's order is preserved", () => {
  const views = toAuditEventViews([
    withEvent({ id: "a" }),
    withEvent({ id: "b" }),
    withEvent({ id: "c" }),
  ]);

  expect(views.map((view) => view.id)).toEqual(["a", "b", "c"]);
});

// -- pagination ------------------------------------------------------------------------------

function pageOf(items: HospitalAuditEvent[], nextCursor: string | null): HospitalAuditPage {
  return { items, nextCursor };
}

test("a cursor means another page exists", () => {
  expect(hasMorePages(pageOf([], "cursor-abc"))).toBe(true);
  expect(hasMorePages(pageOf([EVENT], null))).toBe(false);
  expect(hasMorePages(null)).toBe(false);
});

test("a loaded page is appended after what is already on screen", () => {
  const first = [withEvent({ id: "a" }), withEvent({ id: "b" })];
  const second = [withEvent({ id: "c" })];

  expect(appendPage(first, second).map((event) => event.id)).toEqual(["a", "b", "c"]);
});

test("a repeated row is never appended twice", () => {
  // Keyset pagination does not repeat rows, so a duplicate would mean a double-fired
  // request — and a compliance view showing one event twice is a defect.
  const first = [withEvent({ id: "a" })];

  expect(appendPage(first, [withEvent({ id: "a" })]).map((e) => e.id)).toEqual(["a"]);
});

test("the first page is taken as-is", () => {
  const page = [withEvent({ id: "a" })];

  expect(appendPage([], page)).toBe(page);
});

// -- page copy -------------------------------------------------------------------------------

test("the page never claims to be a complete activity log", () => {
  expect(SCOPE_NOTE).toContain("not a complete record");
  expect(PAGE_DESCRIPTION).toContain("patient-record access");
});

test("the empty state says nothing was recorded, not that nothing was accessed", () => {
  expect(EMPTY_TITLE).toBe("No audit activity yet");
  expect(EMPTY_BODY).toContain("will appear here");
  expect(EMPTY_BODY.toLowerCase()).not.toContain("no records accessed");
});
