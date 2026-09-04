// Backend clinician profile → what the dashboard renders. Pure functions, no React.

import type { Tone } from "@/components/shell/StatusBadge";

import type { DoctorProfile, DoctorStatus } from "./api";

/** Shown when the profile carries no specialty — the column is nullable. */
export const NO_SPECIALTY = "Not recorded";

const STATUS_BADGES: Readonly<Record<DoctorStatus, { label: string; tone: Tone }>> = {
  ACTIVE: { label: "Active", tone: "success" },
  PENDING: { label: "Pending activation", tone: "warning" },
  DISABLED: { label: "Suspended", tone: "destructive" },
};

export interface DoctorIdentityView {
  fullName: string;
  specialty: string;
  hasSpecialty: boolean;
  hospitalName: string;
  registrationNumber: string;
  statusLabel: string;
  statusTone: Tone;
  /** ADR-015: only an ACTIVE clinician may act clinically — including searching. */
  canSearch: boolean;
}

export function toIdentityView(profile: DoctorProfile): DoctorIdentityView {
  const specialty = profile.specialty?.trim();
  const badge = STATUS_BADGES[profile.status];
  return {
    fullName: profile.fullName,
    specialty: specialty === undefined || specialty.length === 0 ? NO_SPECIALTY : specialty,
    hasSpecialty: specialty !== undefined && specialty.length > 0,
    hospitalName: profile.hospital.name,
    registrationNumber: profile.registrationNumber,
    statusLabel: badge.label,
    statusTone: badge.tone,
    canSearch: profile.status === "ACTIVE",
  };
}

/** First word of the clinician's name, for the greeting. */
export function firstNameOf(fullName: string): string {
  const [first] = fullName.trim().split(/\s+/);
  return first !== undefined && first.length > 0 ? first : "Doctor";
}
