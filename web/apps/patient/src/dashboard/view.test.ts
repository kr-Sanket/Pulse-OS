import { expect, test } from "vitest";

import type { AuditEvent } from "@/audit/api";
import type { AccessRequest } from "@/consent/api";
import type { Grant } from "@/grants/api";
import type { RecordMetadata } from "@/records/api";

import {
  firstNameOf,
  GREETING_FALLBACK_NAME,
  summarize,
  toActivityEntries,
  toExpiringGrants,
  toGrantGroups,
  toRecordEntries,
  toReviewRequests,
  type StatSource,
} from "./view";

const NOW = Date.parse("2026-09-03T12:00:00Z");
const DAY = 24 * 60 * 60 * 1000;

function iso(offsetDays: number): string {
  return new Date(NOW + offsetDays * DAY).toISOString();
}

const LABELS = new Map([
  ["CBC", "Complete Blood Count"],
  ["MRI", "MRI Scan"],
]);

const RECORD: RecordMetadata = {
  id: "rec-1",
  categoryCode: "CBC",
  categoryDisplayName: "Complete Blood Count",
  origin: "HOSPITAL_UPLOAD",
  dateOfService: "2026-08-24",
  description: "Routine count",
  originalFilename: "cbc.pdf",
  contentType: "application/pdf",
  sizeBytes: 1024,
  processingStatus: "UPLOADED",
  uploadedByHospital: { hid: "HID-0001", name: "TMH Jamshedpur" },
  createdAt: "2026-08-24T10:00:00Z",
};

const REQUEST: AccessRequest = {
  id: "req-1",
  status: "PENDING",
  purpose: "Cardiology consultation",
  categoryCodes: ["CBC"],
  requesterDoctorId: "doc-1",
  requesterHospitalId: "hos-1",
  expiresAt: iso(6),
  createdAt: iso(-1),
  requester: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
  requesterHospitalName: "Apollo Hospitals",
};

const GRANT: Grant = {
  id: "grant-1",
  categoryCode: "CBC",
  granteeDoctorId: "doc-1",
  grantedAt: "2026-08-15T10:00:00Z",
  expiresAt: iso(3),
  revokedAt: null,
  status: "ACTIVE",
  grantee: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
};

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

function source<T>(items: readonly T[], overrides: Partial<StatSource<T>> = {}): StatSource<T> {
  return { status: "ready", items, truncated: false, ...overrides };
}

test("the greeting uses the first name, and degrades when there is none", () => {
  expect(firstNameOf("Aarav Sharma")).toBe("Aarav");
  expect(firstNameOf("   ")).toBe(GREETING_FALLBACK_NAME);
  expect(firstNameOf(null)).toBe(GREETING_FALLBACK_NAME);
});

test("recent records are styled exactly as the Records page styles them", () => {
  const [entry] = toRecordEntries([RECORD]);

  expect(entry?.title).toBe("cbc.pdf");
  expect(entry?.description).toBe("TMH Jamshedpur · 24 Aug 2026");
  expect(entry?.badgeLabel).toBe("Complete Blood Count");
  expect(entry?.to).toBe("/records");
});

test("recent activity reuses the audit vocabulary rather than restating it", () => {
  const [entry] = toActivityEntries([EVENT], LABELS, NOW);

  expect(entry?.title).toBe("Apollo");
  expect(entry?.description).toBe("Dr Meera Sharma · Cardiology · Complete Blood Count");
  expect(entry?.badgeLabel).toBe("Viewed");
  expect(entry?.timestamp).toBe("2 hours ago");
  expect(entry?.to).toBe("/audit");
});

test("the patient's own events read as You on the dashboard too", () => {
  const own: AuditEvent = {
    ...EVENT,
    actorRole: "PATIENT",
    actor: null,
    action: "CONSENT_APPROVED",
  };

  const [entry] = toActivityEntries([own], LABELS, NOW);

  expect(entry?.title).toBe("You");
  expect(entry?.badgeLabel).toBe("Consent approved");
});

test("the review queue holds only what is actually waiting", () => {
  const requests = [REQUEST, { ...REQUEST, id: "req-2", status: "DECIDED" as const }];

  const queue = toReviewRequests(requests, NOW);

  expect(queue).toHaveLength(1);
  expect(queue[0]?.requester).toBe("Dr Meera Sharma · Cardiology · Apollo Hospitals");
  expect(queue[0]?.purpose).toBe("Cardiology consultation");
});

test("a request about to lapse is flagged, one with time left is not", () => {
  const soon = { ...REQUEST, expiresAt: new Date(NOW + 3 * 60 * 60 * 1000).toISOString() };

  expect(toReviewRequests([soon], NOW)[0]?.urgent).toBe(true);
  expect(toReviewRequests([REQUEST], NOW)[0]?.urgent).toBe(false);
});

test("expiring grants reuse the Grants page grouping and its seven-day rule", () => {
  const groups = toGrantGroups(
    [GRANT, { ...GRANT, id: "grant-2", categoryCode: "MRI" }],
    LABELS,
    NOW,
  );

  const expiring = toExpiringGrants(groups);

  // One approval, two categories → one card.
  expect(expiring).toHaveLength(1);
  expect(expiring[0]?.grantee).toBe("Dr Meera Sharma · Cardiology");
  expect(expiring[0]?.scope).toBe("Complete Blood Count, MRI Scan · Apollo");
  expect(expiring[0]?.expiresIn).toBe("3 days remaining");
});

test("a grant lapsing far off is not called expiring", () => {
  const groups = toGrantGroups([{ ...GRANT, expiresAt: iso(60) }], LABELS, NOW);

  expect(toExpiringGrants(groups)).toEqual([]);
});

test("the nearest expiry comes first", () => {
  const groups = toGrantGroups(
    [
      { ...GRANT, id: "a", expiresAt: iso(6) },
      { ...GRANT, id: "b", grantedAt: "2026-08-16T10:00:00Z", expiresAt: iso(2) },
    ],
    LABELS,
    NOW,
  );

  expect(toExpiringGrants(groups).map((grant) => grant.expiresIn)).toEqual([
    "2 days remaining",
    "6 days remaining",
  ]);
});

test("figures count the loaded page and say so when it is not everything", () => {
  const stats = summarize({
    records: source([RECORD, RECORD]),
    requests: source([REQUEST]),
    grants: source(toGrantGroups([GRANT], LABELS, NOW)),
    events: source([EVENT]),
    now: NOW,
  });
  const byId = new Map(stats.map((stat) => [stat.id, stat]));

  expect(byId.get("records")?.value).toBe("2");
  expect(byId.get("records")?.note).toBe("In your account");
  expect(byId.get("pending")?.value).toBe("1");
  expect(byId.get("grants")?.value).toBe("1");
  expect(byId.get("grants")?.note).toBe("1 expiring soon");
  expect(byId.get("activity")?.value).toBe("2 hours ago");
});

test("a truncated page never claims to be an account total", () => {
  const stats = summarize({
    records: source([RECORD], { truncated: true }),
    requests: source([]),
    grants: source([]),
    events: source([]),
    now: NOW,
  });

  expect(stats.find((stat) => stat.id === "records")?.note).toBe("Most recent page only");
});

test("one failed source leaves its figure unavailable and the others intact", () => {
  const stats = summarize({
    records: source([RECORD]),
    requests: source([], { status: "error" }),
    grants: source([], { status: "loading" }),
    events: source([EVENT]),
    now: NOW,
  });
  const byId = new Map(stats.map((stat) => [stat.id, stat]));

  expect(byId.get("records")?.status).toBe("ready");
  expect(byId.get("requests" as string)).toBeUndefined();
  expect(byId.get("pending")?.status).toBe("unavailable");
  expect(byId.get("pending")?.note).toBe("Unavailable right now");
  expect(byId.get("grants")?.status).toBe("loading");
  expect(byId.get("activity")?.status).toBe("ready");
});

test("an empty account reads as empty, not as missing", () => {
  const stats = summarize({
    records: source([]),
    requests: source([]),
    grants: source([]),
    events: source([]),
    now: NOW,
  });
  const byId = new Map(stats.map((stat) => [stat.id, stat]));

  expect(byId.get("records")?.value).toBe("0");
  expect(byId.get("pending")?.note).toBe("Nothing waiting on you");
  expect(byId.get("activity")?.value).toBe("—");
  expect(byId.get("activity")?.note).toBe("Nothing recorded yet");
});
