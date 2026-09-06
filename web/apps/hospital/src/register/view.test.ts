import { expect, test } from "vitest";

import {
  MAX_ADMIN_FULL_NAME_LENGTH,
  MAX_HOSPITAL_ADDRESS_LENGTH,
  MAX_HOSPITAL_NAME_LENGTH,
  type HospitalRegistrationDraft,
} from "./api";
import {
  DUPLICATE_WARNING,
  EMPTY_DRAFT,
  REGISTERED,
  draftProblems,
  fieldProblem,
  isSendable,
} from "./view";

const VALID: HospitalRegistrationDraft = {
  hospitalName: "Tata Main Hospital",
  hospitalAddress: "Bistupur, Jamshedpur",
  adminFullName: "Anita Rao",
};

function withDraft(overrides: Partial<HospitalRegistrationDraft>): HospitalRegistrationDraft {
  return { ...VALID, ...overrides };
}

test("a complete draft is sendable and reports no problems", () => {
  expect(draftProblems(VALID)).toEqual({});
  expect(isSendable(VALID)).toBe(true);
});

test("an untouched draft is not sendable", () => {
  expect(isSendable(EMPTY_DRAFT)).toBe(false);
  expect(Object.keys(draftProblems(EMPTY_DRAFT)).sort()).toEqual(["adminFullName", "hospitalName"]);
});

test("the address is optional — it is the only field the API accepts as absent", () => {
  expect(fieldProblem("hospitalAddress", "")).toBeNull();
  expect(isSendable(withDraft({ hospitalAddress: "" }))).toBe(true);
});

test("whitespace is not a value", () => {
  expect(fieldProblem("hospitalName", "   ")).toBe("Hospital name is required.");
  expect(isSendable(withDraft({ adminFullName: "  " }))).toBe(false);
});

test("each field is held to the API's own limit, measured after trimming", () => {
  const limits: [keyof HospitalRegistrationDraft, number][] = [
    ["hospitalName", MAX_HOSPITAL_NAME_LENGTH],
    ["hospitalAddress", MAX_HOSPITAL_ADDRESS_LENGTH],
    ["adminFullName", MAX_ADMIN_FULL_NAME_LENGTH],
  ];
  for (const [field, limit] of limits) {
    expect(fieldProblem(field, "x".repeat(limit))).toBeNull();
    expect(fieldProblem(field, "x".repeat(limit + 1))).toContain(`${limit} characters or fewer`);
    // Trailing space must not push a value that fits over its limit.
    expect(fieldProblem(field, `${"x".repeat(limit)} `)).toBeNull();
  }
});

test("the form warns that registering creates a new hospital, not a second administrator", () => {
  // There is no endpoint that adds an administrator to an existing hospital, so an
  // administrator who does not read this ends up with a duplicate organisation.
  expect(DUPLICATE_WARNING).toContain("creates a new hospital");
  expect(DUPLICATE_WARNING).toContain("existing");
});

test("the success panel names who verifies and what is blocked until they do", () => {
  expect(REGISTERED.body).toContain("system administrator");
  expect(REGISTERED.points.join(" ")).toContain("doctors cannot register");
});
