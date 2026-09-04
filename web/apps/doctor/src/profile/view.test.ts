import { expect, test } from "vitest";

import type { DoctorProfile } from "./api";
import { firstNameOf, NO_SPECIALTY, STATUS_NOTICES, toIdentityView } from "./view";

const PROFILE: DoctorProfile = {
  fullName: "Meera Sharma",
  specialty: "Cardiology",
  registrationNumber: "REG-4471",
  status: "ACTIVE",
  hospital: {
    hid: "HID-0003",
    name: "Apollo Hospitals",
    address: null,
    verificationStatus: "VERIFIED",
    createdAt: "2026-07-01T10:00:00Z",
  },
  createdAt: "2026-07-02T10:00:00Z",
};

function withProfile(overrides: Partial<DoctorProfile>): DoctorProfile {
  return { ...PROFILE, ...overrides };
}

test("an active clinician is shown as active and may search", () => {
  const view = toIdentityView(PROFILE);

  expect(view.fullName).toBe("Meera Sharma");
  expect(view.hospitalName).toBe("Apollo Hospitals");
  expect(view.specialty).toBe("Cardiology");
  expect(view.statusLabel).toBe("Active");
  expect(view.statusTone).toBe("success");
  expect(view.canSearch).toBe(true);
});

test("a pending or suspended clinician may not search (ADR-015)", () => {
  const pending = toIdentityView(withProfile({ status: "PENDING" }));
  const disabled = toIdentityView(withProfile({ status: "DISABLED" }));

  expect(pending.statusLabel).toBe("Pending activation");
  expect(pending.statusTone).toBe("warning");
  expect(pending.canSearch).toBe(false);
  expect(disabled.statusLabel).toBe("Suspended");
  expect(disabled.statusTone).toBe("destructive");
  expect(disabled.canSearch).toBe(false);
});

test("a missing specialty is stated, not invented", () => {
  expect(toIdentityView(withProfile({ specialty: null })).specialty).toBe(NO_SPECIALTY);
  expect(toIdentityView(withProfile({ specialty: "  " })).hasSpecialty).toBe(false);
});

test("the greeting uses the first name", () => {
  expect(firstNameOf("Meera Sharma")).toBe("Meera");
  expect(firstNameOf("   ")).toBe("Doctor");
});

// -- hospital facts -----------------------------------------------------------------------

test("the hospital is identified by name and by its public HID", () => {
  const view = toIdentityView(PROFILE);

  expect(view.hospitalName).toBe("Apollo Hospitals");
  expect(view.hospitalHid).toBe("HID-0003");
});

test("a verified hospital reads as verified; an unverified one says so", () => {
  const verified = toIdentityView(PROFILE);
  const pending = toIdentityView(
    withProfile({ hospital: { ...PROFILE.hospital, verificationStatus: "PENDING" } }),
  );

  expect(verified.hospitalVerificationLabel).toBe("Verified");
  expect(verified.hospitalVerificationTone).toBe("success");
  expect(pending.hospitalVerificationLabel).toBe("Pending verification");
  expect(pending.hospitalVerificationTone).toBe("warning");
});

// -- status messaging ---------------------------------------------------------------------

test("an active clinician is told nothing, because nothing is wrong", () => {
  expect(toIdentityView(PROFILE).statusNotice).toBeNull();
  expect(STATUS_NOTICES.ACTIVE).toBeNull();
});

test("a pending clinician is told who can activate them", () => {
  const notice = toIdentityView(withProfile({ status: "PENDING" })).statusNotice;

  expect(notice).toBe(STATUS_NOTICES.PENDING);
  expect(notice).toContain("pending activation");
  expect(notice).toContain("hospital administrator");
});

test("a suspended clinician is told they are suspended, not that they are pending", () => {
  const notice = toIdentityView(withProfile({ status: "DISABLED" })).statusNotice;

  expect(notice).toBe(STATUS_NOTICES.DISABLED);
  expect(notice).toContain("suspended");
  expect(notice).not.toContain("pending activation");
});

test("the notice and the search gate agree about every status", () => {
  for (const status of ["ACTIVE", "PENDING", "DISABLED"] as const) {
    const view = toIdentityView(withProfile({ status }));
    expect(view.canSearch).toBe(view.statusNotice === null);
  }
});
