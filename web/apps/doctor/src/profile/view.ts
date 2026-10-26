// Backend clinician profile → what the dashboard and the profile page render. Pure
// functions, no React, so every rule below is unit-tested.

import type { Tone } from "@/components/shell/StatusBadge";

import type { DoctorProfile, DoctorStatus } from "./api";

/** Shown when the profile carries no specialty — the column is nullable. */
export const NO_SPECIALTY = "Not recorded";

/**
 * What a clinician needs to be told about their own status, or null when nothing is wrong.
 *
 * One sentence per state, in one place, so the dashboard and the profile page cannot drift
 * into saying different things about the same account. ADR-015: only an ACTIVE clinician
 * holds any clinical capability, and only a hospital administrator can change that.
 */
export const STATUS_NOTICES: Readonly<Record<DoctorStatus, string | null>> = {
  ACTIVE: null,
  PENDING:
    "Your clinician profile is pending activation. A hospital administrator must activate " +
    "it before you can look up patients.",
  DISABLED:
    "Your clinician profile is suspended. A hospital administrator must reactivate it " +
    "before you can look up patients.",
};

const STATUS_BADGES: Readonly<Record<DoctorStatus, { label: string; tone: Tone }>> = {
  ACTIVE: { label: "Active", tone: "success" },
  PENDING: { label: "Pending activation", tone: "warning" },
  DISABLED: { label: "Suspended", tone: "destructive" },
};

type HospitalVerification = DoctorProfile["hospital"]["verificationStatus"];

const VERIFICATION_BADGES: Readonly<Record<HospitalVerification, { label: string; tone: Tone }>> = {
  VERIFIED: { label: "Verified", tone: "success" },
  PENDING: { label: "Pending verification", tone: "warning" },
  // ADR-034. A clinician can only have joined a VERIFIED hospital, so REJECTED is reachable
  // only through data repair; SUSPENDED is the hospital pausing new hospital-level operations.
  SUSPENDED: { label: "Suspended", tone: "warning" },
  REJECTED: { label: "Rejected", tone: "destructive" },
};

export interface DoctorIdentityView {
  fullName: string;
  specialty: string;
  hasSpecialty: boolean;
  hospitalName: string;
  registrationNumber: string;
  statusLabel: string;
  statusTone: Tone;
  /** What to tell the clinician about their status, or null when it needs no explanation. */
  statusNotice: string | null;
  /** ADR-015: only an ACTIVE clinician may act clinically — including searching. */
  canSearch: boolean;
  /** The hospital's public identifier, `HID-XXXX`. */
  hospitalHid: string;
  hospitalVerificationLabel: string;
  hospitalVerificationTone: Tone;
}

export function toIdentityView(profile: DoctorProfile): DoctorIdentityView {
  const specialty = profile.specialty?.trim();
  const badge = STATUS_BADGES[profile.status];
  const verification = VERIFICATION_BADGES[profile.hospital.verificationStatus];
  return {
    fullName: profile.fullName,
    specialty: specialty === undefined || specialty.length === 0 ? NO_SPECIALTY : specialty,
    hasSpecialty: specialty !== undefined && specialty.length > 0,
    hospitalName: profile.hospital.name,
    registrationNumber: profile.registrationNumber,
    statusLabel: badge.label,
    statusTone: badge.tone,
    statusNotice: STATUS_NOTICES[profile.status],
    canSearch: profile.status === "ACTIVE",
    hospitalHid: profile.hospital.hid,
    hospitalVerificationLabel: verification.label,
    hospitalVerificationTone: verification.tone,
  };
}

/** First word of the clinician's name, for the greeting. */
export function firstNameOf(fullName: string): string {
  const [first] = fullName.trim().split(/\s+/);
  return first !== undefined && first.length > 0 ? first : "Doctor";
}
