import { expect, test } from "vitest";

import type { AuditEvent } from "./api";
import {
  actionPresentation,
  humanizeAction,
  NO_CATEGORY,
  originOf,
  SELF_ACTOR,
  summarize,
  toEventView,
  toEventViews,
} from "./view";

const NOW = Date.parse("2026-09-03T12:00:00Z");

const EVENT: AuditEvent = {
  id: "evt-1",
  action: "RECORD_VIEWED",
  actorUserId: "user-1",
  actorRole: "DOCTOR",
  actor: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
  targetRecordId: "rec-1",
  targetCategoryCode: "CBC",
  targetRequestId: null,
  occurredAt: "2026-09-03T10:00:00Z",
  eventHash: "3f9a1c77d2b40e15a6c3f8091b2d4e6a7c8b9d0e1f2a3b4c5d6e7f8091a2b3c4",
};

const LABELS = new Map([["CBC", "Complete Blood Count"]]);

function withEvent(overrides: Partial<AuditEvent>): AuditEvent {
  return { ...EVENT, ...overrides };
}

test("every backend action has its own wording and tone", () => {
  expect(actionPresentation("RECORD_VIEWED")).toEqual({ label: "Viewed", tone: "info" });
  expect(actionPresentation("ACCESS_DENIED")).toEqual({
    label: "Access denied",
    tone: "destructive",
  });
  expect(actionPresentation("CONSENT_REVOKED").label).toBe("Access withdrawn");
});

test("an action added server-side after this build degrades instead of breaking", () => {
  expect(humanizeAction("EMERGENCY_ACCESS")).toBe("Emergency access");
  expect(actionPresentation("EMERGENCY_ACCESS")).toEqual({
    label: "Emergency access",
    tone: "neutral",
  });
});

test("the patient's own actions read as You, with nothing beneath", () => {
  expect(originOf(withEvent({ actorRole: "PATIENT", actor: null }))).toEqual({
    origin: SELF_ACTOR,
    actor: null,
  });
});

test("hospital staff read as their hospital, with their name beneath", () => {
  expect(originOf(EVENT)).toEqual({ origin: "Apollo", actor: "Dr Meera Sharma · Cardiology" });
  const noSpecialty = withEvent({
    actor: { fullName: "Rina Admin", specialty: null, hospitalName: "TMH" },
    actorRole: "HOSPITAL_ADMIN",
  });
  expect(originOf(noSpecialty)).toEqual({ origin: "TMH", actor: "Rina Admin" });
});

test("an actor the projection cannot name falls back to the role it recorded", () => {
  expect(originOf(withEvent({ actor: null })).origin).toBe("A clinician");
  expect(originOf(withEvent({ actor: null, actorRole: "HOSPITAL_ADMIN" })).origin).toBe(
    "Hospital staff",
  );
});

test("the category renders as a display name, and its absence is stated", () => {
  expect(toEventView(EVENT, LABELS).category).toBe("Complete Blood Count");
  expect(toEventView(EVENT, LABELS).hasCategory).toBe(true);

  const noCategory = toEventView(withEvent({ targetCategoryCode: null }), LABELS);
  expect(noCategory.category).toBe(NO_CATEGORY);
  expect(noCategory.hasCategory).toBe(false);
});

test("a category this build has never seen renders as its code", () => {
  expect(toEventView(withEvent({ targetCategoryCode: "GENOME" }), LABELS).category).toBe("GENOME");
});

test("the tamper-evidence digest is previewed, and kept whole for the title", () => {
  const view = toEventView(EVENT, LABELS);

  expect(view.hashPreview).toBe("3f9a1c…b3c4");
  expect(view.eventHash).toBe(EVENT.eventHash);
});

test("the summary counts only the events on this page and says so", () => {
  const events = [
    EVENT,
    withEvent({ id: "evt-2", action: "RECORD_DOWNLOADED" }),
    withEvent({
      id: "evt-3",
      actorRole: "PATIENT",
      actor: null,
      action: "CONSENT_APPROVED",
      targetCategoryCode: null,
    }),
  ];

  const summary = summarize(events, toEventViews(events, LABELS), NOW);
  const byId = new Map(summary.map((stat) => [stat.id, stat]));

  expect(byId.get("loaded")?.value).toBe("3");
  expect(byId.get("loaded")?.note).toBe("On this page only");
  // The patient is not an organisation, so their own action is not counted as one.
  expect(byId.get("organisations")?.value).toBe("1");
  expect(byId.get("organisations")?.note).toBe("Apollo");
  expect(byId.get("busiest")?.value).toBe("2");
  expect(byId.get("busiest")?.note).toBe("Complete Blood Count");
  expect(byId.get("latest")?.value).toBe("2 hours ago");
  expect(byId.get("latest")?.note).toBe("Viewed");
});

test("an empty page summarises to nothing rather than to zeroes that look like totals", () => {
  const summary = summarize([], [], NOW);
  const byId = new Map(summary.map((stat) => [stat.id, stat]));

  expect(byId.get("loaded")?.value).toBe("0");
  expect(byId.get("busiest")?.value).toBe("—");
  expect(byId.get("busiest")?.note).toBe("No category recorded");
  expect(byId.get("latest")?.value).toBe("—");
  expect(byId.get("latest")?.note).toBe("Nothing recorded yet");
});

test("events with no category at all leave the busiest figure empty", () => {
  const events = [withEvent({ targetCategoryCode: null })];

  const summary = summarize(events, toEventViews(events, LABELS), NOW);

  expect(summary.find((stat) => stat.id === "busiest")?.value).toBe("—");
});
