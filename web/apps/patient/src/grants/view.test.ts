import { expect, test } from "vitest";

import type { Grant } from "./api";
import {
  applyRevocations,
  bucketGrants,
  daysUntil,
  EXPIRING_SOON_DAYS,
  groupGrants,
  groupKey,
  UNKNOWN_CLINICIAN,
  UNKNOWN_HOSPITAL,
} from "./view";

const NOW = Date.parse("2026-09-03T12:00:00Z");
const DAY = 24 * 60 * 60 * 1000;

function iso(offsetDays: number): string {
  return new Date(NOW + offsetDays * DAY).toISOString();
}

const GRANT: Grant = {
  id: "grant-1",
  categoryCode: "CBC",
  granteeDoctorId: "doc-1",
  grantedAt: "2026-08-15T10:00:00Z",
  expiresAt: iso(30),
  revokedAt: null,
  status: "ACTIVE",
  grantee: { fullName: "Dr Meera Sharma", specialty: "Cardiology", hospitalName: "Apollo" },
};

const LABELS = new Map([
  ["CBC", "Complete Blood Count"],
  ["MRI", "MRI Scan"],
]);

function withGrant(overrides: Partial<Grant>): Grant {
  return { ...GRANT, ...overrides };
}

test("the grouping key is the grantee, the two timestamps and the status", () => {
  expect(groupKey(GRANT)).toBe(`doc-1|2026-08-15T10:00:00Z|${iso(30)}|ACTIVE`);
});

test("rows from one approval become one card carrying every category", () => {
  const groups = groupGrants(
    [GRANT, withGrant({ id: "grant-2", categoryCode: "MRI" })],
    LABELS,
    NOW,
  );

  expect(groups).toHaveLength(1);
  expect(groups[0]?.grantIds).toEqual(["grant-1", "grant-2"]);
  expect(groups[0]?.categories).toEqual(["Complete Blood Count", "MRI Scan"]);
});

test("a different grantee, moment or expiry is a different card", () => {
  const groups = groupGrants(
    [
      GRANT,
      withGrant({ id: "b", granteeDoctorId: "doc-2" }),
      withGrant({ id: "c", grantedAt: "2026-08-16T10:00:00Z" }),
      withGrant({ id: "d", expiresAt: iso(60) }),
    ],
    LABELS,
    NOW,
  );

  expect(groups).toHaveLength(4);
});

test("a half-withdrawn approval stays two cards, so neither claims the other's status", () => {
  const groups = groupGrants(
    [GRANT, withGrant({ id: "grant-2", categoryCode: "MRI", status: "REVOKED" })],
    LABELS,
    NOW,
  );

  expect(groups.map((group) => group.status)).toEqual(["ACTIVE", "REVOKED"]);
});

test("a category this build has never seen renders as its code", () => {
  const groups = groupGrants([withGrant({ categoryCode: "GENOME" })], LABELS, NOW);

  expect(groups[0]?.categories).toEqual(["GENOME"]);
});

test("purpose is absent because a grant does not carry one", () => {
  expect(groupGrants([GRANT], LABELS, NOW)[0]?.purpose).toBeNull();
});

test("an unresolved grantee is stated, not invented", () => {
  const groups = groupGrants([withGrant({ grantee: null })], LABELS, NOW);

  expect(groups[0]?.hospital).toBe(UNKNOWN_HOSPITAL);
  expect(groups[0]?.clinician).toBe(UNKNOWN_CLINICIAN);
});

test("the clinician line carries the specialty only when the record has one", () => {
  expect(groupGrants([GRANT], LABELS, NOW)[0]?.clinician).toBe("Dr Meera Sharma · Cardiology");
  const plain = withGrant({
    grantee: { fullName: "Dr Rao", specialty: null, hospitalName: "TMH" },
  });
  expect(groupGrants([plain], LABELS, NOW)[0]?.clinician).toBe("Dr Rao");
});

test("days remaining rounds up, so a grant lapsing tonight has a day left", () => {
  expect(daysUntil(iso(6), NOW)).toBe(6);
  expect(daysUntil(new Date(NOW + 6 * 60 * 60 * 1000).toISOString(), NOW)).toBe(1);
  expect(daysUntil("not-a-date", NOW)).toBeNull();
});

test("expiring soon is the next seven days, and only for a live grant", () => {
  const soon = groupGrants([withGrant({ expiresAt: iso(EXPIRING_SOON_DAYS) })], LABELS, NOW);
  const later = groupGrants([withGrant({ expiresAt: iso(EXPIRING_SOON_DAYS + 1) })], LABELS, NOW);
  const gone = groupGrants(
    [withGrant({ status: "REVOKED", revokedAt: iso(-1), expiresAt: iso(2) })],
    LABELS,
    NOW,
  );

  expect(soon[0]?.expiringSoon).toBe(true);
  expect(later[0]?.expiringSoon).toBe(false);
  expect(gone[0]?.expiringSoon).toBe(false);
  expect(gone[0]?.daysRemaining).toBeNull();
});

test("expiring soon is a filtered view of active — the same objects, not copies", () => {
  const groups = groupGrants(
    [GRANT, withGrant({ id: "b", grantedAt: "2026-08-20T10:00:00Z", expiresAt: iso(3) })],
    LABELS,
    NOW,
  );

  const buckets = bucketGrants(groups);

  expect(buckets.active).toHaveLength(2);
  expect(buckets.expiringSoon).toHaveLength(1);
  // Identity, not equality: the card in both lists is one object.
  expect(buckets.expiringSoon[0]).toBe(buckets.active[1]);
});

test("each status lands in its own section", () => {
  const buckets = bucketGrants(
    groupGrants(
      [
        GRANT,
        withGrant({ id: "b", granteeDoctorId: "doc-2", status: "REVOKED", revokedAt: iso(-1) }),
        withGrant({ id: "c", granteeDoctorId: "doc-3", status: "EXPIRED" }),
      ],
      LABELS,
      NOW,
    ),
  );

  expect(buckets.active.map((group) => group.grantIds)).toEqual([["grant-1"]]);
  expect(buckets.revoked.map((group) => group.grantIds)).toEqual([["b"]]);
  expect(buckets.expired.map((group) => group.grantIds)).toEqual([["c"]]);
});

test("the compact card's two facts are worded for the grant's own status", () => {
  const active = groupGrants([withGrant({ expiresAt: iso(1) })], LABELS, NOW)[0];
  const revoked = groupGrants(
    [withGrant({ status: "REVOKED", revokedAt: "2026-09-02T10:00:00Z" })],
    LABELS,
    NOW,
  )[0];

  expect(active?.summaryNote).toBe("1 day remaining");
  expect(active?.summaryDetail).toContain("Expires");
  expect(revoked?.summaryNote).toContain("Withdrawn");
  expect(revoked?.summaryDetail).toContain("Granted");
});

test("a withdrawal recorded this session re-files the card without a refetch", () => {
  const rows = [GRANT, withGrant({ id: "grant-2", categoryCode: "MRI" })];

  const applied = applyRevocations(rows, new Set(["grant-1", "grant-2"]), iso(0));
  const buckets = bucketGrants(groupGrants(applied, LABELS, NOW));

  expect(buckets.active).toEqual([]);
  expect(buckets.revoked).toHaveLength(1);
  expect(buckets.revoked[0]?.grantIds).toEqual(["grant-1", "grant-2"]);
});

test("applying no withdrawals leaves the rows untouched", () => {
  const rows = [GRANT];

  expect(applyRevocations(rows, new Set(), iso(0))).toBe(rows);
});
