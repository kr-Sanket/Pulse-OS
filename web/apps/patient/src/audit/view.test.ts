import { expect, test } from "vitest";

import type { AuditEvent } from "./api";
import {
  actionPresentation,
  countOwnRecordAccess,
  filterAuditEntries,
  humanizeAction,
  isOwnRecordAccess,
  groupAuditEvents,
  groupedEventCount,
  initialExpansion,
  NO_CATEGORY,
  NO_EXTERNAL_ACCESS,
  originOf,
  SELF_ORIGIN,
  SELF_ACTOR,
  summarizeAuditEntries,
  toEventView,
  toEventViews,
  UNATTRIBUTED_ORIGIN,
} from "./view";

const NOW = Date.parse("2026-09-03T12:00:00Z");
/** Newer than every other fixture instant, for the "most recent" assertions. */
const NEWEST = "2026-09-03T11:30:00Z";

const EVENT: AuditEvent = {
  id: "evt-1",
  action: "RECORD_VIEWED",
  actorUserId: "user-1",
  actorRole: "DOCTOR",
  actor: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
  // The hospital the event was attributed to when written, which is what the trail groups
  // on. Deliberately *not* the same as `actor.hospitalName` above: the fixtures disagree so
  // that any test reading the wrong one fails (ADR-025).
  actorHospital: { hid: "HID-0001", name: "TMH Jamshedpur" },
  targetRecordId: "rec-1",
  targetCategoryCode: "CBC",
  targetRequestId: null,
  occurredAt: "2026-09-03T10:00:00Z",
  eventHash: "3f9a1c77d2b40e15a6c3f8091b2d4e6a7c8b9d0e1f2a3b4c5d6e7f8091a2b3c4",
  // No anchor yet: the backend nulls all three anchor fields exactly when NOT_ANCHORED.
  integrity: { status: "NOT_ANCHORED", network: null, reference: null, anchoredAt: null },
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

test("the origin is the hospital recorded on the event, not where the actor works now", () => {
  // **The ADR-025 rule.** The fixture's actor currently works at Apollo; the event was
  // written at TMH Jamshedpur. Reading `actor.hospitalName` here would move a clinician's
  // past activity to a new employer the day they changed jobs.
  expect(EVENT.actor?.hospitalName).toBe("Apollo");
  expect(originOf(EVENT)).toEqual({
    origin: "TMH Jamshedpur",
    actor: "Dr Meera Sharma · Cardiology",
  });

  const noSpecialty = withEvent({
    actor: { fullName: "Rina Admin", specialty: null, hospitalName: "Apollo" },
    actorHospital: { hid: "HID-0002", name: "CMC Vellore" },
    actorRole: "HOSPITAL_ADMIN",
  });
  expect(originOf(noSpecialty)).toEqual({ origin: "CMC Vellore", actor: "Rina Admin" });
});

test("an event with no recorded hospital says so rather than borrowing the actor's", () => {
  const legacy = withEvent({ actorHospital: null });
  // The actor is still named and still has a current employer — neither may stand in.
  expect(legacy.actor?.hospitalName).toBe("Apollo");
  expect(originOf(legacy)).toEqual({
    origin: UNATTRIBUTED_ORIGIN,
    actor: "Dr Meera Sharma · Cardiology",
  });
});

test("an actor the projection cannot name still groups by its recorded hospital", () => {
  expect(originOf(withEvent({ actor: null }))).toEqual({
    origin: "TMH Jamshedpur",
    actor: null,
  });
  expect(originOf(withEvent({ actor: null, actorHospital: null })).origin).toBe(
    UNATTRIBUTED_ORIGIN,
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

  const summary = summarizeAuditEntries(events, toEventViews(events, LABELS), {
    showOwnActivity: true,
    now: NOW,
  });
  const byId = new Map(summary.map((stat) => [stat.id, stat]));

  expect(byId.get("loaded")?.value).toBe("3");
  expect(byId.get("loaded")?.note).toBe("On this page only");
  // The patient is not an organisation, so their own action is not counted as one.
  expect(byId.get("organisations")?.value).toBe("1");
  // The organisation counted is the one recorded on the event (ADR-025), so the summary
  // and the groups beneath it can never name different hospitals for the same activity.
  expect(byId.get("organisations")?.note).toBe("TMH Jamshedpur");
  expect(byId.get("busiest")?.value).toBe("2");
  expect(byId.get("busiest")?.note).toBe("Complete Blood Count");
  expect(byId.get("latest")?.value).toBe("2 hours ago");
  expect(byId.get("latest")?.note).toBe("Viewed");
});

test("an empty page summarises to nothing rather than to zeroes that look like totals", () => {
  const summary = summarizeAuditEntries([], [], { showOwnActivity: true, now: NOW });
  const byId = new Map(summary.map((stat) => [stat.id, stat]));

  expect(byId.get("loaded")?.value).toBe("0");
  expect(byId.get("busiest")?.value).toBe("—");
  expect(byId.get("busiest")?.note).toBe("No category recorded");
  expect(byId.get("latest")?.value).toBe("—");
  expect(byId.get("latest")?.note).toBe("Nothing recorded yet");
});

test("events with no category at all leave the busiest figure empty", () => {
  const events = [withEvent({ targetCategoryCode: null })];

  const summary = summarizeAuditEntries(events, toEventViews(events, LABELS), {
    showOwnActivity: true,
    now: NOW,
  });

  expect(summary.find((stat) => stat.id === "busiest")?.value).toBe("—");
});

// -- the default view: who else touched my records? ------------------------------------------

const MINE = { actorRole: "PATIENT", actor: null } as const;

test("the patient's own reads and downloads are hidden by default", () => {
  const events = [
    withEvent({ id: "own-view", ...MINE, action: "RECORD_VIEWED" }),
    withEvent({ id: "own-download", ...MINE, action: "RECORD_DOWNLOADED" }),
  ];

  expect(events.map(isOwnRecordAccess)).toEqual([true, true]);
  expect(filterAuditEntries(events, false)).toEqual([]);
});

test("the same actions by a clinician are exactly what the page is for", () => {
  const events = [
    withEvent({ id: "doc-view", actorRole: "DOCTOR", action: "RECORD_VIEWED" }),
    withEvent({ id: "doc-download", actorRole: "DOCTOR", action: "RECORD_DOWNLOADED" }),
    withEvent({ id: "doc-listed", actorRole: "DOCTOR", action: "RECORDS_LISTED" }),
  ];

  expect(events.map(isOwnRecordAccess)).toEqual([false, false, false]);
  expect(filterAuditEntries(events, false).map((event) => event.id)).toEqual([
    "doc-view",
    "doc-download",
    "doc-listed",
  ]);
});

test("hospital activity is never hidden", () => {
  const events = [
    withEvent({ id: "upload", actorRole: "HOSPITAL_ADMIN", action: "RECORD_UPLOADED" }),
    withEvent({ id: "admin-view", actorRole: "HOSPITAL_ADMIN", action: "RECORD_VIEWED" }),
  ];

  expect(filterAuditEntries(events, false).map((event) => event.id)).toEqual([
    "upload",
    "admin-view",
  ]);
});

test("consent events stay visible even when the patient is the one who acted", () => {
  // Approving access is not the same kind of event as reading a page: it is precisely what
  // this trail exists to evidence, so it survives the filter that hides the patient's reads.
  const events = [
    withEvent({ id: "approved", ...MINE, action: "CONSENT_APPROVED" }),
    withEvent({ id: "rejected", ...MINE, action: "CONSENT_REJECTED" }),
    withEvent({ id: "revoked", ...MINE, action: "CONSENT_REVOKED" }),
    withEvent({ id: "requested", actorRole: "DOCTOR", action: "ACCESS_REQUESTED" }),
    withEvent({ id: "denied", actorRole: "DOCTOR", action: "ACCESS_DENIED" }),
  ];

  expect(filterAuditEntries(events, false).map((event) => event.id)).toEqual([
    "approved",
    "rejected",
    "revoked",
    "requested",
    "denied",
  ]);
});

test("turning the switch on returns the page exactly as the API sent it", () => {
  const events = [
    withEvent({ id: "doc-view", actorRole: "DOCTOR" }),
    withEvent({ id: "own-view", ...MINE, action: "RECORD_VIEWED" }),
    withEvent({ id: "own-download", ...MINE, action: "RECORD_DOWNLOADED" }),
  ];

  expect(filterAuditEntries(events, true)).toEqual(events);
});

test("filtering preserves the trail's order — a reordered audit log is a different document", () => {
  const events = [
    withEvent({ id: "a", actorRole: "DOCTOR", occurredAt: "2026-09-03T11:00:00Z" }),
    withEvent({ id: "own", ...MINE, action: "RECORD_VIEWED", occurredAt: "2026-09-03T10:30:00Z" }),
    withEvent({ id: "b", actorRole: "HOSPITAL_ADMIN", occurredAt: "2026-09-03T10:00:00Z" }),
    withEvent({ id: "own-2", ...MINE, action: "RECORD_DOWNLOADED" }),
    withEvent({ id: "c", actorRole: "DOCTOR", occurredAt: "2026-09-03T09:00:00Z" }),
  ];

  expect(filterAuditEntries(events, false).map((event) => event.id)).toEqual(["a", "b", "c"]);
});

test("the hidden count is what the switch offers to reveal", () => {
  const events = [
    withEvent({ id: "a", actorRole: "DOCTOR" }),
    withEvent({ id: "own", ...MINE, action: "RECORD_VIEWED" }),
    withEvent({ id: "own-2", ...MINE, action: "RECORD_DOWNLOADED" }),
    withEvent({ id: "consent", ...MINE, action: "CONSENT_APPROVED" }),
  ];

  expect(countOwnRecordAccess(events)).toBe(2);
  expect(countOwnRecordAccess([])).toBe(0);
  // Nothing hidden means an empty timeline is genuinely empty, not filtered.
  expect(countOwnRecordAccess([withEvent({ actorRole: "DOCTOR" })])).toBe(0);
});

test("the summary counts the rows on screen, not the ones the filter removed", () => {
  const events = [
    withEvent({
      id: "doc-view",
      actorRole: "DOCTOR",
      targetCategoryCode: "CBC",
      occurredAt: "2026-09-03T10:00:00Z",
    }),
    withEvent({ id: "own-1", ...MINE, action: "RECORD_VIEWED", targetCategoryCode: "CBC" }),
    withEvent({ id: "own-2", ...MINE, action: "RECORD_DOWNLOADED", targetCategoryCode: "CBC" }),
  ];

  const visible = filterAuditEntries(events, false);
  const filtered = new Map(
    summarizeAuditEntries(visible, toEventViews(visible, LABELS), {
      showOwnActivity: false,
      now: NOW,
    }).map((stat) => [stat.id, stat]),
  );

  expect(filtered.get("loaded")?.value).toBe("1");
  expect(filtered.get("loaded")?.note).toBe("Excluding your own reads");
  // Three CBC events were fetched; only the visible one is counted.
  expect(filtered.get("busiest")?.value).toBe("1");
  expect(filtered.get("organisations")?.value).toBe("1");

  const all = new Map(
    summarizeAuditEntries(events, toEventViews(events, LABELS), {
      showOwnActivity: true,
      now: NOW,
    }).map((stat) => [stat.id, stat]),
  );

  expect(all.get("loaded")?.value).toBe("3");
  expect(all.get("loaded")?.note).toBe("On this page only");
  expect(all.get("busiest")?.value).toBe("3");
});

test("the most recent event follows the filter rather than the fetch", () => {
  const events = [
    withEvent({ id: "own", ...MINE, action: "RECORD_DOWNLOADED", occurredAt: NEWEST }),
    withEvent({ id: "doc", actorRole: "DOCTOR", occurredAt: "2026-09-03T10:00:00Z" }),
  ];

  const visible = filterAuditEntries(events, false);
  const summary = summarizeAuditEntries(visible, toEventViews(visible, LABELS), {
    showOwnActivity: false,
    now: NOW,
  });

  // The patient's own download is newer, but it is not on screen, so it is not "most recent".
  expect(summary.find((stat) => stat.id === "latest")?.note).toBe("Viewed");
});

test("an empty timeline is detectable, and its copy names the question the page answers", () => {
  const onlyMine = [
    withEvent({ id: "own", ...MINE, action: "RECORD_VIEWED" }),
    withEvent({ id: "own-2", ...MINE, action: "RECORD_DOWNLOADED" }),
  ];

  // Filtered to nothing, but with something to reveal.
  expect(filterAuditEntries(onlyMine, false)).toHaveLength(0);
  expect(countOwnRecordAccess(onlyMine)).toBe(2);
  // Genuinely nothing recorded: the same empty state, with nothing to reveal.
  expect(filterAuditEntries([], false)).toHaveLength(0);
  expect(countOwnRecordAccess([])).toBe(0);

  expect(NO_EXTERNAL_ACCESS.title).toBe("No external access yet");
  expect(NO_EXTERNAL_ACCESS.body).toBe(
    "No doctors, hospitals or other users have accessed your records yet.",
  );
  expect(NO_EXTERNAL_ACCESS.action).toBe("Show my activity");
});

// -- grouping ---------------------------------------------------------------------------

const TMH = { hid: "HID-0001", name: "TMH Jamshedpur" };
const CMC = { hid: "HID-0002", name: "CMC Vellore" };

/** A trail spanning both hospitals, two clinicians at one of them, an unattributed legacy
 * event and the patient's own read — every branch of `originKeyOf` in one fixture. */
function trail(): AuditEvent[] {
  return [
    withEvent({
      id: "a",
      actorUserId: "verma",
      actorHospital: TMH,
      occurredAt: "2026-09-08T11:42:00Z",
    }),
    withEvent({
      id: "b",
      actorUserId: "verma",
      actorHospital: TMH,
      occurredAt: "2026-09-08T11:40:00Z",
    }),
    withEvent({
      id: "c",
      actorUserId: "nair",
      actorHospital: TMH,
      occurredAt: "2026-09-07T09:00:00Z",
    }),
    withEvent({
      id: "d",
      actorUserId: "george",
      actorHospital: CMC,
      occurredAt: "2026-09-06T09:00:00Z",
    }),
    withEvent({
      id: "e",
      actorUserId: "ghost",
      actorHospital: null,
      occurredAt: "2026-09-05T09:00:00Z",
    }),
    withEvent({
      id: "f",
      actorRole: "PATIENT",
      actor: null,
      actorHospital: null,
      occurredAt: "2026-09-04T09:00:00Z",
    }),
  ];
}

test("events group by recorded hospital, then by actor, newest group first", () => {
  const groups = groupAuditEvents(trail(), LABELS);

  expect(groups.map((group) => group.title)).toEqual([
    "TMH Jamshedpur",
    "CMC Vellore",
    UNATTRIBUTED_ORIGIN,
    SELF_ORIGIN,
  ]);
  expect(groups.map((group) => group.kind)).toEqual([
    "hospital",
    "hospital",
    "unattributed",
    "self",
  ]);
  const tmh = groups[0]!;
  expect(tmh.eventCount).toBe(3);
  expect(tmh.actors.map((actor) => actor.key)).toEqual(["verma", "nair"]); // newest actor first
  expect(tmh.actors[0]!.eventCount).toBe(2);
  expect(tmh.actors[0]!.events.map((event) => event.id)).toEqual(["a", "b"]); // newest event first
  expect(tmh.latestAt).toBe("2026-09-08T11:42:00Z");
});

test("every visible event appears exactly once and the counts sum to the input", () => {
  // The invariant the whole design rests on: grouping is a rearrangement, never a filter.
  const events = trail();
  const groups = groupAuditEvents(events, LABELS);

  const ids = groups.flatMap((group) => group.actors.flatMap((a) => a.events.map((e) => e.id)));
  expect(ids).toHaveLength(events.length);
  expect(new Set(ids)).toEqual(new Set(events.map((event) => event.id)));
  expect(groupedEventCount(groups)).toBe(events.length);
  for (const group of groups) {
    expect(group.eventCount).toBe(
      group.actors.reduce((total, actor) => total + actor.events.length, 0),
    );
  }
});

test("a legacy event is never absorbed into a hospital, and never invents one", () => {
  const groups = groupAuditEvents(trail(), LABELS);
  const unattributed = groups.find((group) => group.kind === "unattributed")!;

  expect(unattributed.eventCount).toBe(1);
  expect(unattributed.actors[0]!.events[0]!.id).toBe("e");
  // Its actor still works somewhere — that hospital must not have claimed the event.
  expect(groups.filter((group) => group.kind === "hospital").map((g) => g.title)).toEqual([
    "TMH Jamshedpur",
    "CMC Vellore",
  ]);
});

test("the patient's own events form their own group and get no hospital", () => {
  const groups = groupAuditEvents(trail(), LABELS);
  const own = groups.find((group) => group.kind === "self")!;

  expect(own.title).toBe(SELF_ORIGIN);
  expect(own.eventCount).toBe(1);
  expect(own.actors).toHaveLength(1);
  expect(own.actors[0]!.name).toBe(SELF_ACTOR);
});

test("filtering happens before grouping, so a hidden row inflates no count", () => {
  const events = [
    ...trail(),
    withEvent({ id: "own-read", actorRole: "PATIENT", actor: null, actorHospital: null }),
  ];
  const visible = filterAuditEntries(events, false);
  const groups = groupAuditEvents(visible, LABELS);

  expect(groupedEventCount(groups)).toBe(visible.length);
  // Both patient rows are RECORD_VIEWED, so the default view drops both and the group has
  // nothing left to hold — it must vanish rather than render as "Your own activity · 0".
  expect(groups.find((group) => group.kind === "self")).toBeUndefined();
  expect(groupedEventCount(groups)).toBe(events.length - 2);
  // Toggling on restores every event, grouped and counted in full.
  expect(groupedEventCount(groupAuditEvents(events, LABELS))).toBe(events.length);
  const withOwn = groupAuditEvents(filterAuditEntries(events, true), LABELS);
  expect(withOwn.find((group) => group.kind === "self")?.eventCount).toBe(2);
});

test("a group whose every event is filtered out disappears rather than rendering empty", () => {
  const onlyOwnReads = [
    withEvent({ id: "x", actorRole: "PATIENT", actor: null, actorHospital: null }),
  ];
  expect(groupAuditEvents(filterAuditEntries(onlyOwnReads, false), LABELS)).toEqual([]);
});

test("the same actor at two hospitals is two groups, keyed per hospital", () => {
  const moved = [
    withEvent({
      id: "later",
      actorUserId: "verma",
      actorHospital: CMC,
      occurredAt: "2026-09-09T09:00:00Z",
    }),
    withEvent({
      id: "earlier",
      actorUserId: "verma",
      actorHospital: TMH,
      occurredAt: "2026-09-01T09:00:00Z",
    }),
  ];
  const groups = groupAuditEvents(moved, LABELS);

  expect(groups.map((group) => group.title)).toEqual(["CMC Vellore", "TMH Jamshedpur"]);
  expect(groups.every((group) => group.actors.length === 1)).toBe(true);
  expect(groupedEventCount(groups)).toBe(2);
});

test("the newest hospital and its newest actor start expanded, nothing else", () => {
  const groups = groupAuditEvents(trail(), LABELS);
  const expansion = initialExpansion(groups);

  expect(expansion.origins).toEqual(["HID-0001"]);
  expect(expansion.actors).toEqual(["HID-0001/verma"]);
});

test("an empty trail expands nothing", () => {
  expect(initialExpansion([])).toEqual({ origins: [], actors: [] });
});
