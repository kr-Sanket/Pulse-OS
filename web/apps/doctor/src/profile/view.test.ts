import { expect, test } from "vitest";

import type { DoctorProfile } from "./api";
import { firstNameOf, NO_SPECIALTY, toIdentityView } from "./view";

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
