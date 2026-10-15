import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";

import { ActiveGrantCard } from "./ActiveGrantCard";
import type { Grant } from "@/grants/api";
import { groupGrants } from "@/grants/view";

const RAW_GRANT_1: Grant = {
  id: "g-1",
  categoryCode: "BLOOD_WORK",
  granteeDoctorId: "doc-1",
  grantedAt: "2026-10-01T10:00:00Z",
  expiresAt: "2026-11-01T10:00:00Z",
  revokedAt: null,
  status: "ACTIVE",
  grantee: {
    fullName: "Dr. Gregory House",
    specialty: "Diagnostics",
    hospitalName: "Memorial General Hospital",
  },
};

const RAW_GRANT_2: Grant = {
  ...RAW_GRANT_1,
  id: "g-2",
  categoryCode: "PRESCRIPTION",
};

const LABELS = new Map([
  ["BLOOD_WORK", "Blood Work"],
  ["PRESCRIPTION", "Prescriptions"],
]);
const BASE_GRANT = groupGrants(
  [RAW_GRANT_1, RAW_GRANT_2],
  LABELS,
  Date.parse("2026-10-15T12:00:00Z"),
)[0]!;

test("1. Renders active grant details with hospital, clinician, and shared categories", () => {
  const onRevoke = vi.fn();
  const html = renderToString(
    <ActiveGrantCard grant={BASE_GRANT} busy={false} error={null} onRevoke={onRevoke} />,
  );

  expect(html).toContain("Memorial General Hospital");
  expect(html).toContain("Dr. Gregory House · Diagnostics");
  expect(html).toContain("Blood Work");
  expect(html).toContain("Prescriptions");
  expect(html).toContain("Revoke Access");
});

test("2. Renders Revoke Access action with confirmation button", () => {
  const onRevoke = vi.fn();
  const html = renderToString(
    <ActiveGrantCard grant={BASE_GRANT} busy={false} error={null} onRevoke={onRevoke} />,
  );

  expect(html).toContain("Revoke Access");
  expect(onRevoke).not.toHaveBeenCalled();
});

test("3. Busy state indicates revoking in progress and disables action", () => {
  const onRevoke = vi.fn();
  const html = renderToString(
    <ActiveGrantCard grant={BASE_GRANT} busy={true} error={null} onRevoke={onRevoke} />,
  );

  expect(html).toContain("Revoking…");
  expect(html).toContain('disabled=""');
});

test("4. Error state displays error alert message", () => {
  const onRevoke = vi.fn();
  const errorMessage = "Could not revoke this grant. Please try again.";
  const html = renderToString(
    <ActiveGrantCard grant={BASE_GRANT} busy={false} error={errorMessage} onRevoke={onRevoke} />,
  );

  expect(html).toContain('role="alert"');
  expect(html).toContain(errorMessage);
});
