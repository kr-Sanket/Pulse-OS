import { expect, test } from "vitest";

import {
  MAX_FULL_NAME_LENGTH,
  MAX_HOSPITAL_HID_LENGTH,
  MAX_REGISTRATION_NUMBER_LENGTH,
  MAX_SPECIALTY_LENGTH,
  type DoctorRegistrationDraft,
} from "./api";
import { draftProblems, EMPTY_DRAFT, fieldProblem, isSendable, REGISTERED } from "./view";

const VALID: DoctorRegistrationDraft = {
  fullName: "Dr Meera Sharma",
  registrationNumber: "MCI-2019-44718",
  specialty: "Cardiology",
  hospitalHid: "HID-0001",
};

function withDraft(overrides: Partial<DoctorRegistrationDraft>): DoctorRegistrationDraft {
  return { ...VALID, ...overrides };
}

test("a complete draft is sendable and reports no problems", () => {
  expect(draftProblems(VALID)).toEqual({});
  expect(isSendable(VALID)).toBe(true);
});

test("an untouched draft is not sendable", () => {
  expect(isSendable(EMPTY_DRAFT)).toBe(false);
  expect(Object.keys(draftProblems(EMPTY_DRAFT)).sort()).toEqual([
    "fullName",
    "hospitalHid",
    "registrationNumber",
  ]);
});

test("every required field is required, and whitespace does not satisfy it", () => {
  for (const field of ["fullName", "registrationNumber", "hospitalHid"] as const) {
    expect(fieldProblem(field, "")).toContain("required");
    expect(fieldProblem(field, "   \n ")).toContain("required");
    expect(isSendable(withDraft({ [field]: "  " }))).toBe(false);
  }
});

test("specialty is the one field the API accepts as absent", () => {
  expect(fieldProblem("specialty", "")).toBeNull();
  expect(fieldProblem("specialty", "   ")).toBeNull();
  expect(isSendable(withDraft({ specialty: "" }))).toBe(true);
});

test("each field is measured trimmed, against the API's own limit", () => {
  const limits = {
    fullName: MAX_FULL_NAME_LENGTH,
    registrationNumber: MAX_REGISTRATION_NUMBER_LENGTH,
    specialty: MAX_SPECIALTY_LENGTH,
    hospitalHid: MAX_HOSPITAL_HID_LENGTH,
  } as const;

  for (const [field, limit] of Object.entries(limits) as [keyof typeof limits, number][]) {
    expect(fieldProblem(field, "x".repeat(limit))).toBeNull();
    expect(fieldProblem(field, `  ${"x".repeat(limit)}  `)).toBeNull();
    expect(fieldProblem(field, "x".repeat(limit + 1))).toContain(`${limit} characters`);
  }
});

test("validation stops at shape — it never predicts a backend ruling", () => {
  // A syntactically fine but non-existent hospital passes here; the API answers 422.
  expect(isSendable(withDraft({ hospitalHid: "HID-9999" }))).toBe(true);
  // Lower case is fine too: the api layer uppercases before sending.
  expect(isSendable(withDraft({ hospitalHid: "hid-0001" }))).toBe(true);
});

test("the waiting panel names who acts next and what it unlocks", () => {
  expect(REGISTERED.title).toBe("Registration submitted");
  expect(REGISTERED.body).toContain("hospital administrator");
  expect(REGISTERED.points.join(" ")).toContain("activates your profile");
  expect(REGISTERED.points.join(" ")).toContain("patient search");
});
