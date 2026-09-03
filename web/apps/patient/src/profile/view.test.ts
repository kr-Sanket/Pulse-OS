import { expect, test } from "vitest";

import type { PatientProfile } from "@pulseos/api-client";

import {
  accountFacts,
  NOT_PROVIDED,
  NOT_RECORDED,
  personalInfoFor,
  resolveIdentity,
  securityFacts,
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
