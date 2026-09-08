import { expect, test } from "vitest";

import type { PatientProfile } from "@pulseos/api-client";

import {
  accountFacts,
  NOT_PROVIDED,
  NOT_RECORDED,
  personalInfoFor,
  resolveIdentity,
  securityFacts,
  changedFields,
  draftFrom,
  fieldForWireName,
  GENDER_OPTIONS,
  isDirty,
  validateDraft,
  VALIDATION,
} from "./view";

const PROFILE: PatientProfile = {
  healthId: "PHI-IND-2026-1QE8DVR",
  fullName: "Aarav Sharma",
  dateOfBirth: "1988-03-14",
  gender: "MALE",
  createdAt: "2026-07-12T09:30:00Z",
};

const USER = {
  displayName: "A. Sharma (Google)",
  email: "aarav@example.test",
  photoURL: "https://photos.test/aarav.jpg",
};

function withProfile(overrides: Partial<PatientProfile>): PatientProfile {
  return { ...PROFILE, ...overrides };
}

function fieldsFor(profile: PatientProfile): Map<string, string> {
  const identity = resolveIdentity(profile, USER);
  return new Map(personalInfoFor(profile, identity).map((field) => [field.label, field.value]));
}

test("the name comes from the health record, the email and avatar from the identity", () => {
  expect(resolveIdentity(PROFILE, USER)).toEqual({
    fullName: "Aarav Sharma",
    email: "aarav@example.test",
    photoURL: "https://photos.test/aarav.jpg",
  });
});

test("a signed-in identity without an email or photo degrades rather than breaking", () => {
  const identity = resolveIdentity(PROFILE, { displayName: null, email: "  ", photoURL: null });

  expect(identity).toEqual({
    fullName: "Aarav Sharma",
    email: NOT_PROVIDED,
    photoURL: null,
  });
});

test("account facts carry the Health ID and a formatted member-since date", () => {
  expect(accountFacts(PROFILE)).toEqual({
    healthId: "PHI-IND-2026-1QE8DVR",
    status: "Active",
    memberSince: "12 July 2026",
  });
});

test("personal information keeps every row, backed or not", () => {
  const fields = fieldsFor(PROFILE);

  expect([...fields.keys()]).toEqual([
    "Full Name",
    "Email",
    "Phone Number",
    "Date of Birth",
    "Gender",
    "Blood Group",
    "Health ID",
    "Nationality",
    "Address",
  ]);
});

test("backed fields render their value; unmodelled ones say so", () => {
  const fields = fieldsFor(PROFILE);

  expect(fields.get("Full Name")).toBe("Aarav Sharma");
  expect(fields.get("Date of Birth")).toBe("14 March 1988");
  expect(fields.get("Gender")).toBe("Male");
  expect(fields.get("Health ID")).toBe("PHI-IND-2026-1QE8DVR");
  expect(fields.get("Phone Number")).toBe(NOT_PROVIDED);
  expect(fields.get("Blood Group")).toBe(NOT_RECORDED);
  expect(fields.get("Nationality")).toBe(NOT_RECORDED);
  expect(fields.get("Address")).toBe(NOT_PROVIDED);
});

test("a nullable backend field reads as missing, not as a blank", () => {
  const fields = fieldsFor(withProfile({ dateOfBirth: null, gender: null }));

  expect(fields.get("Date of Birth")).toBe(NOT_PROVIDED);
  expect(fields.get("Gender")).toBe(NOT_PROVIDED);
});

test("FHIR's UNKNOWN gender is an absence, not a value to display", () => {
  expect(fieldsFor(withProfile({ gender: "UNKNOWN" })).get("Gender")).toBe(NOT_RECORDED);
});

test("unmodelled and empty fields are marked so the card can mute them", () => {
  const identity = resolveIdentity(withProfile({ dateOfBirth: null }), USER);
  const missing = personalInfoFor(withProfile({ dateOfBirth: null }), identity)
    .filter((field) => field.missing === true)
    .map((field) => field.label);

  expect(missing).toEqual([
    "Phone Number",
    "Date of Birth",
    "Blood Group",
    "Nationality",
    "Address",
  ]);
});

test("the Health ID is monospaced and the address spans the row", () => {
  const identity = resolveIdentity(PROFILE, USER);
  const fields = personalInfoFor(PROFILE, identity);

  expect(fields.find((field) => field.label === "Health ID")?.mono).toBe(true);
  expect(fields.find((field) => field.label === "Address")?.wide).toBe(true);
});

test("security facts claim only what the app can stand behind", () => {
  const facts = securityFacts(resolveIdentity(PROFILE, USER));

  expect(facts.map((fact) => fact.label)).toEqual([
    "Authentication Method",
    "Sign-in Email",
    "Two-Factor Authentication",
    "Account Status",
  ]);
  expect(facts.find((fact) => fact.label === "Sign-in Email")?.value).toBe("aarav@example.test");
  expect(facts.find((fact) => fact.label === "Account Status")?.tone).toBe("success");
});

// -- editing ----------------------------------------------------------------------------

const EDITABLE: PatientProfile = {
  healthId: "PHI-IND-2026-J0TA0DK",
  fullName: "Joaquin141 Rice937",
  dateOfBirth: "1962-08-27",
  gender: "MALE",
  createdAt: "2026-09-07T18:34:01Z",
};

const TODAY = new Date("2026-09-08T12:00:00Z");

test("the draft is seeded from the profile, with nulls as empty strings", () => {
  expect(draftFrom(EDITABLE)).toEqual({
    fullName: "Joaquin141 Rice937",
    dateOfBirth: "1962-08-27",
    gender: "MALE",
  });
  expect(draftFrom({ ...EDITABLE, dateOfBirth: null, gender: null })).toEqual({
    fullName: "Joaquin141 Rice937",
    dateOfBirth: "",
    gender: "",
  });
});

test("dirty tracking survives typing a change and undoing it", () => {
  const clean = draftFrom(EDITABLE);
  expect(isDirty(EDITABLE, clean)).toBe(false);
  expect(isDirty(EDITABLE, { ...clean, fullName: "Joaquin Rice" })).toBe(true);
  // Whitespace-only edits are not changes: the API trims, so saving one would be a no-op.
  expect(isDirty(EDITABLE, { ...clean, fullName: "  Joaquin141 Rice937  " })).toBe(false);
  expect(isDirty(EDITABLE, { ...clean, dateOfBirth: "" })).toBe(true);
  expect(isDirty(EDITABLE, { ...clean, gender: "" })).toBe(true);
});

test("only changed fields are sent, and clearing one sends an explicit null", () => {
  const clean = draftFrom(EDITABLE);
  expect(changedFields(EDITABLE, clean)).toEqual({});
  expect(changedFields(EDITABLE, { ...clean, fullName: "  Joaquin Rice  " })).toEqual({
    fullName: "Joaquin Rice",
  });
  // Omitted means "leave alone"; null means "clear" — the distinction the API relies on.
  expect(changedFields(EDITABLE, { ...clean, dateOfBirth: "", gender: "" })).toEqual({
    dateOfBirth: null,
    gender: null,
  });
  expect(changedFields(EDITABLE, { ...clean, gender: "FEMALE" })).toEqual({ gender: "FEMALE" });
});

test("validation mirrors the API's rules", () => {
  const clean = draftFrom(EDITABLE);
  expect(validateDraft(clean, TODAY)).toEqual({});
  expect(validateDraft({ ...clean, fullName: "" }, TODAY).fullName).toBe(VALIDATION.nameRequired);
  expect(validateDraft({ ...clean, fullName: "   " }, TODAY).fullName).toBe(
    VALIDATION.nameRequired,
  );
  expect(validateDraft({ ...clean, fullName: "x".repeat(121) }, TODAY).fullName).toBe(
    VALIDATION.nameTooLong,
  );
  expect(validateDraft({ ...clean, fullName: "x".repeat(120) }, TODAY).fullName).toBeUndefined();
});

test("a future date of birth is refused, today included, and a cleared one is fine", () => {
  const clean = draftFrom(EDITABLE);
  expect(validateDraft({ ...clean, dateOfBirth: "2099-01-01" }, TODAY).dateOfBirth).toBe(
    VALIDATION.dateOfBirthFuture,
  );
  // The API's rule is `>= today`, so today itself is not a valid date of birth.
  expect(validateDraft({ ...clean, dateOfBirth: "2026-09-08" }, TODAY).dateOfBirth).toBe(
    VALIDATION.dateOfBirthFuture,
  );
  expect(validateDraft({ ...clean, dateOfBirth: "2026-09-07" }, TODAY).dateOfBirth).toBeUndefined();
  expect(validateDraft({ ...clean, dateOfBirth: "" }, TODAY).dateOfBirth).toBeUndefined();
});

test("the gender options offer the API vocabulary plus an explicit not-provided", () => {
  expect(GENDER_OPTIONS.map((option) => option.value)).toEqual([
    "",
    "MALE",
    "FEMALE",
    "OTHER",
    "UNKNOWN",
  ]);
});

test("server field names map back onto the input they belong to", () => {
  expect(fieldForWireName("fullName")).toBe("fullName");
  expect(fieldForWireName("dateOfBirth")).toBe("dateOfBirth");
  expect(fieldForWireName("gender")).toBe("gender");
  // Anything else falls through to the form-level message rather than a wrong field.
  expect(fieldForWireName("healthId")).toBeNull();
  expect(fieldForWireName("body")).toBeNull();
});

test("immutable facts are never part of the editable draft", () => {
  // The compiler enforces this, but the test states the intent: a draft has three keys.
  expect(Object.keys(draftFrom(EDITABLE)).sort()).toEqual(["dateOfBirth", "fullName", "gender"]);
  expect(changedFields(EDITABLE, { ...draftFrom(EDITABLE), fullName: "New" })).not.toHaveProperty(
    "healthId",
  );
});
