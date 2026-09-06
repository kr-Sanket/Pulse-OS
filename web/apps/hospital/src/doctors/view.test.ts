import { expect, test } from "vitest";

import type { Doctor } from "./api";
import {
  DOCTOR_SECTIONS,
  NO_SPECIALTY,
  actionFor,
  applyStatusChanges,
  bucketOf,
  groupDoctors,
  statusLabel,
  toDoctorView,
  toDoctorViews,
} from "./view";

const DOCTOR: Doctor = {
  id: "11111111-1111-4111-8111-111111111111",
  fullName: "Meera Sharma",
  specialty: "Cardiology",
  registrationNumber: "MCI-2019-44718",
  status: "PENDING",
  createdAt: "2026-07-02T10:00:00Z",
};

function withDoctor(overrides: Partial<Doctor>): Doctor {
  return { ...DOCTOR, ...overrides };
}

test("a doctor row maps to what the card renders", () => {
  const view = toDoctorView(DOCTOR);

  expect(view.fullName).toBe("Meera Sharma");
  expect(view.specialty).toBe("Cardiology");
  expect(view.hasSpecialty).toBe(true);
  expect(view.registrationNumber).toBe("MCI-2019-44718");
  expect(view.registeredOn).not.toContain("T");
});

test("the status vocabulary matches what the doctor portal shows the doctor themselves", () => {
  // An administrator and a clinician must never read two different words for one state.
  expect(statusLabel("ACTIVE")).toBe("Active");
  expect(statusLabel("PENDING")).toBe("Pending activation");
  expect(statusLabel("DISABLED")).toBe("Suspended");
});

test("a missing or blank specialty is reported as not recorded, never as empty", () => {
  expect(toDoctorView(withDoctor({ specialty: null })).specialty).toBe(NO_SPECIALTY);
  expect(toDoctorView(withDoctor({ specialty: "  " })).specialty).toBe(NO_SPECIALTY);
  expect(toDoctorView(withDoctor({ specialty: null })).hasSpecialty).toBe(false);
});

test("each status offers exactly the action that moves it", () => {
  expect(actionFor("PENDING")).toMatchObject({ kind: "activate", label: "Activate" });
  expect(actionFor("DISABLED")).toMatchObject({ kind: "activate", label: "Reactivate" });
  expect(actionFor("ACTIVE")).toMatchObject({ kind: "deactivate", label: "Suspend" });
});

test("activation is described as permission to ask, never as access", () => {
  // The dangerous misreading: an administrator believing activation shares records.
  expect(actionFor("PENDING").effect).toContain("grants no record access");
  expect(actionFor("PENDING").effect).toContain("consent");
});

test("suspension is described as immediate, and as not withdrawing consent", () => {
  // consent.enforce refuses a suspended clinician even where a live grant survives, and no
  // grant is touched — so reactivating restores access without anyone consenting again.
  const effect = actionFor("ACTIVE").effect;
  expect(effect).toContain("even where a patient has already granted access");
  expect(effect).toContain("No consent is withdrawn");
});

test("the roster is sectioned with whoever is waiting on the administrator first", () => {
  expect(DOCTOR_SECTIONS.map((section) => section.bucket)).toEqual([
    "pending",
    "active",
    "suspended",
  ]);
  expect(bucketOf("DISABLED")).toBe("suspended");
});

test("doctors are filed under their section, keeping the API's order", () => {
  const views = toDoctorViews([
    withDoctor({ id: "a", status: "ACTIVE" }),
    withDoctor({ id: "b", status: "PENDING" }),
    withDoctor({ id: "c", status: "ACTIVE" }),
    withDoctor({ id: "d", status: "DISABLED" }),
  ]);

  const buckets = groupDoctors(views);

  expect(buckets.active.map((view) => view.id)).toEqual(["a", "c"]);
  expect(buckets.pending.map((view) => view.id)).toEqual(["b"]);
  expect(buckets.suspended.map((view) => view.id)).toEqual(["d"]);
});

test("a status changed this session re-files the card without a refetch", () => {
  const doctors = [withDoctor({ id: "a", status: "PENDING" }), withDoctor({ id: "b" })];

  const applied = applyStatusChanges(doctors, new Map([["a", "ACTIVE"]]));

  expect(applied[0]?.status).toBe("ACTIVE");
  expect(groupDoctors(toDoctorViews(applied)).active.map((view) => view.id)).toEqual(["a"]);
});

test("applying no changes returns the rows untouched", () => {
  const doctors = [DOCTOR];

  expect(applyStatusChanges(doctors, new Map())).toBe(doctors);
  // A change that matches what the row already says must not clone it either.
  expect(applyStatusChanges(doctors, new Map([["x", "ACTIVE"]]))[0]).toBe(DOCTOR);
});
