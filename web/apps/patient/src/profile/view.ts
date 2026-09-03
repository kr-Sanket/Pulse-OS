// Backend patient profile + the signed-in Firebase identity → what the account cards
// render.
//
// Two sources, deliberately: GET /patients/me owns the health record (Health ID, legal
// name, date of birth, gender, when the account was created), and the identity provider
// owns the sign-in facts PulseOS never stores (email address, avatar). Anything neither
// of them knows is stated as missing rather than invented — the backend models no phone,
// blood group, nationality, address or emergency contact (docs/DOMAIN_MODEL.md §1), and a
// health record is the last place to show a plausible-looking placeholder.
//
// Pure functions, no React, so every rule below is unit-testable.

import type { PatientProfile } from "@pulseos/api-client";

import type { Tone } from "@/components/dashboard/StatusBadge";

/** Shown where the profile has no value and the backend has no column for one. */
export const NOT_PROVIDED = "Not provided";

/** Shown for facts PulseOS does not model at all, as opposed to ones left blank. */
export const NOT_RECORDED = "Not recorded";

/** The shape resolveIdentity accepts — structurally an AuthUser, without the dependency. */
export interface SignedInIdentity {
  displayName: string | null;
  email: string | null;
  photoURL: string | null;
}

/** The identity facts the cards render, after both sources are reconciled. */
export interface ProfileIdentity {
  fullName: string;
  email: string;
  photoURL: string | null;
}

/**
 * The patient's name comes from their PulseOS record, not from Google: it is the name the
 * Health ID was issued against, and the one a hospital sees. Email and avatar have no
 * backend column, so they can only come from the identity provider.
 */
export function resolveIdentity(
  profile: PatientProfile,
  user: SignedInIdentity | null,
): ProfileIdentity {
  const email = user?.email?.trim();
  return {
    fullName: profile.fullName,
    email: email === undefined || email.length === 0 ? NOT_PROVIDED : email,
    photoURL: user?.photoURL ?? null,
  };
}

const ACCOUNT_DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

const BIRTH_DATE = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "long",
  year: "numeric",
  // A date of birth is a calendar date with no time zone; formatting it locally would
  // shift it a day west of Greenwich.
  timeZone: "UTC",
});

function format(formatter: Intl.DateTimeFormat, iso: string): string {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? iso : formatter.format(parsed);
}

const GENDER_LABELS: Readonly<Record<PatientProfile["gender"] & string, string>> = {
  MALE: "Male",
  FEMALE: "Female",
  OTHER: "Other",
  // FHIR's "unknown" means the record does not carry it — not a gender to display.
  UNKNOWN: NOT_RECORDED,
};

export interface AccountFacts {
  healthId: string;
  status: string;
  memberSince: string;
}

/**
 * Account-level facts. `status` is derived, not stored: the API answered with a profile
 * for this token, which is the whole of what "active" means to PulseOS today — there is
 * no status column on the patient row.
 */
export function accountFacts(profile: PatientProfile): AccountFacts {
  return {
    healthId: profile.healthId,
    status: "Active",
    memberSince: format(ACCOUNT_DATE, profile.createdAt),
  };
}

export interface ProfileField {
  label: string;
  value: string;
  /** Fixed-width, for identifiers that are read character by character. */
  mono?: boolean;
  /** Spans the full row rather than one grid column — for long values. */
  wide?: boolean;
  /** Nothing behind this field yet: rendered muted so absence is legible as absence. */
  missing?: boolean;
}

/** The Personal Information list: backend fields first, then the ones nothing feeds yet. */
export function personalInfoFor(
  profile: PatientProfile,
  identity: ProfileIdentity,
): readonly ProfileField[] {
  const dateOfBirth = profile.dateOfBirth;
  const gender = profile.gender;
  return [
    { label: "Full Name", value: identity.fullName },
    { label: "Email", value: identity.email, missing: identity.email === NOT_PROVIDED },
    { label: "Phone Number", value: NOT_PROVIDED, missing: true },
    {
      label: "Date of Birth",
      value: dateOfBirth === null ? NOT_PROVIDED : format(BIRTH_DATE, dateOfBirth),
      missing: dateOfBirth === null,
    },
    {
      label: "Gender",
      value: gender === null ? NOT_PROVIDED : GENDER_LABELS[gender],
      missing: gender === null || gender === "UNKNOWN",
    },
    { label: "Blood Group", value: NOT_RECORDED, missing: true },
    { label: "Health ID", value: profile.healthId, mono: true },
    { label: "Nationality", value: NOT_RECORDED, missing: true },
    { label: "Address", value: NOT_PROVIDED, wide: true, missing: true },
  ];
}

export interface SecurityFact {
  label: string;
  value: string;
  /** When set, the value renders as a tone badge instead of plain text. */
  tone?: Tone;
}

/**
 * How this account is secured. Only facts the app can actually stand behind: sign-in is
 * Google's (ADR-011) and the profile loaded under this token. Last-login time and email
 * verification are Firebase Admin facts the API does not expose, so neither is claimed.
 */
export function securityFacts(identity: ProfileIdentity): readonly SecurityFact[] {
  return [
    { label: "Authentication Method", value: "Google Sign-In" },
    { label: "Sign-in Email", value: identity.email },
    { label: "Two-Factor Authentication", value: "Managed by your Google Account" },
    { label: "Account Status", value: "Active", tone: "success" },
  ];
}

/** Standing copy for the privacy panel — the one genuinely static thing on this page. */
export const PROFILE_PRIVACY = {
  title: "Profile Information",
  body:
    "Your personal information is encrypted and securely stored. Only healthcare providers " +
    "you authorize can access your medical records.",
  points: [
    "Your Pulse Health ID stays the same at every hospital, so your records follow you.",
    "Every access attempt is recorded in Audit History, including refused ones.",
    "You can withdraw a provider's access at any time from Active Grants.",
  ],
} as const;

/** Copy for the emergency-contact card, which has no backend to read from yet. */
export const EMERGENCY_CONTACT_EMPTY = {
  title: "No emergency contact recorded",
  body: "PulseOS does not store an emergency contact yet. Your hospital keeps the one you gave them at registration.",
} as const;
