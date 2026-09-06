import { expect, test } from "vitest";

import type { HospitalAdminProfile } from "./api";
import { ADMIN_LABEL, NO_ADDRESS, VERIFICATION_NOTICES, firstNameOf, toIdentityView } from "./view";

const PROFILE: HospitalAdminProfile = {
  adminFullName: "Anita Rao",
  hospital: {
    hid: "HID-0001",
    name: "Tata Main Hospital",
    address: "Bistupur, Jamshedpur",
    verificationStatus: "VERIFIED",
    createdAt: "2026-07-01T10:00:00Z",
  },
};

function withHospital(overrides: Partial<HospitalAdminProfile["hospital"]>): HospitalAdminProfile {
  return { ...PROFILE, hospital: { ...PROFILE.hospital, ...overrides } };
}

test("a verified hospital reads as verified and may operate", () => {
  const view = toIdentityView(PROFILE);

  expect(view.hospitalName).toBe("Tata Main Hospital");
  expect(view.hospitalHid).toBe("HID-0001");
  expect(view.adminFullName).toBe("Anita Rao");
  expect(view.address).toBe("Bistupur, Jamshedpur");
  expect(view.hasAddress).toBe(true);
  expect(view.verificationLabel).toBe("Verified");
  expect(view.verificationTone).toBe("success");
  expect(view.canOperate).toBe(true);
});

test("a verified hospital is told nothing, because nothing is wrong", () => {
  expect(toIdentityView(PROFILE).verificationNotice).toBeNull();
  expect(VERIFICATION_NOTICES.VERIFIED).toBeNull();
});

test("a pending hospital may not operate, and is told what that blocks (ADR-015)", () => {
  const view = toIdentityView(withHospital({ verificationStatus: "PENDING" }));

  expect(view.verificationLabel).toBe("Pending verification");
  expect(view.verificationTone).toBe("warning");
  expect(view.canOperate).toBe(false);
  // The two capabilities the backend actually refuses on an unverified hospital: doctor
  // registration and every upload. A notice that named neither would be useless.
  expect(view.verificationNotice).toContain("doctors cannot register");
  expect(view.verificationNotice).toContain("no records can be uploaded");
});

test("a missing or blank address is reported as not recorded, never as empty", () => {
  expect(toIdentityView(withHospital({ address: null })).address).toBe(NO_ADDRESS);
  expect(toIdentityView(withHospital({ address: "   " })).address).toBe(NO_ADDRESS);
  expect(toIdentityView(withHospital({ address: null })).hasAddress).toBe(false);
});

test("the registration date is formatted, not echoed as an ISO string", () => {
  expect(toIdentityView(PROFILE).registeredOn).not.toContain("T");
});

test("the greeting uses the first name, and never renders empty", () => {
  expect(firstNameOf("Anita Rao")).toBe("Anita");
  expect(firstNameOf("  Anita  Rao ")).toBe("Anita");
  expect(firstNameOf("   ")).toBe("there");
});

test("the dashboard label names the administrator of record, not the signed-in account", () => {
  // The name it sits above is `adminFullName` — the hospital's administrator on PulseOS —
  // which is not necessarily the Firebase account that authenticated. The two diverge
  // whenever an administrator did not register their own hospital, and the label must not
  // claim otherwise; the signed-in account is the sidebar footer's job.
  expect(ADMIN_LABEL).toBe("Hospital administrator");
  expect(ADMIN_LABEL.toLowerCase()).not.toContain("signed in");
});
