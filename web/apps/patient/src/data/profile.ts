// Mock profile data for the account page. Static by design: this slice is presentation
// only, so nothing here calls the API.
//
// Three facts are real — display name, email and photo come from the signed-in identity
// (auth/provider.ts) via resolveIdentity below. Everything else stands in for the patient
// profile the backend already models (docs/DOMAIN_MODEL.md §1) and for account facts that
// belong to the identity provider, so wiring this page later is a change of source, not of
// components.

import type { Tone } from "@/components/dashboard/StatusBadge";

/** The identity facts the page renders, after auth values and fallbacks are reconciled. */
export interface ProfileIdentity {
  fullName: string;
  email: string;
  photoURL: string | null;
}

/** The shape resolveIdentity accepts — structurally an AuthUser, without the dependency. */
export interface SignedInIdentity {
  displayName: string | null;
  email: string | null;
  photoURL: string | null;
}

/** Shown only when the signed-in identity carries nothing for that field. */
const IDENTITY_FALLBACK = {
  fullName: "PulseOS Patient",
  email: "Not provided",
} as const;

function textOr(value: string | null | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed.length === 0 ? fallback : trimmed;
}

/** Prefer the authenticated identity; fall back only where it is empty or absent. */
export function resolveIdentity(user: SignedInIdentity | null): ProfileIdentity {
  return {
    fullName: textOr(user?.displayName, IDENTITY_FALLBACK.fullName),
    email: textOr(user?.email, IDENTITY_FALLBACK.email),
    photoURL: user?.photoURL ?? null,
  };
}

/** Account-level facts. The Health ID follows ADR-012's PHI-IND-YYYY-XXXXXXC format. */
export const ACCOUNT = {
  healthId: "PHI-IND-2026-9F3KQ27",
  status: "Active",
  memberSince: "12 July 2026",
} as const;

export interface ProfileField {
  label: string;
  value: string;
  /** Fixed-width, for identifiers that are read character by character. */
  mono?: boolean;
  /** Spans the full row rather than one grid column — for long values. */
  wide?: boolean;
}

/** Everything the identity provider does not know about the patient. */
const PERSONAL_DETAILS: readonly ProfileField[] = [
  { label: "Phone Number", value: "+91 98350 77412" },
  { label: "Date of Birth", value: "8 March 2003" },
  { label: "Gender", value: "Male" },
  { label: "Blood Group", value: "O+" },
  { label: "Health ID", value: ACCOUNT.healthId, mono: true },
  { label: "Nationality", value: "Indian" },
  {
    label: "Address",
    value: "27 Bistupur Main Road, Sakchi, Jamshedpur, Jharkhand 831001, India",
    wide: true,
  },
];

/** The definition list for Personal Information: auth-derived fields first, then mock. */
export function personalInfoFor(identity: ProfileIdentity): readonly ProfileField[] {
  return [
    { label: "Full Name", value: identity.fullName },
    { label: "Email", value: identity.email },
    ...PERSONAL_DETAILS,
  ];
}

export interface EmergencyContact {
  name: string;
  relationship: string;
  phone: string;
  /** Optional — omitted from the card when null. */
  secondaryPhone: string | null;
}

export const EMERGENCY_CONTACT: EmergencyContact = {
  name: "Rina Kumari",
  relationship: "Mother",
  phone: "+91 98350 41122",
  secondaryPhone: "+91 65742 20189",
};

export interface SecurityFact {
  label: string;
  value: string;
  /** When set, the value renders as a tone badge instead of plain text. */
  tone?: Tone;
}

export const SECURITY_FACTS: readonly SecurityFact[] = [
  { label: "Authentication Method", value: "Google Sign-In" },
  { label: "Google Account", value: "Connected", tone: "success" },
  { label: "Verified Email", value: "Verified", tone: "success" },
  { label: "Account Status", value: ACCOUNT.status, tone: "success" },
  { label: "Last Login", value: "Today at 9:14 AM" },
];

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
