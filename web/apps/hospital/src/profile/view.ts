// Backend hospital-admin profile → what the dashboard and the My Hospital page render. Pure
// functions, no React, so every rule below is unit-tested.

import { formatInstantDate } from "@pulseos/ui";

import type { Tone } from "@/components/shell/StatusBadge";

import type { HospitalAdminProfile, HospitalVerificationStatus } from "./api";

/** Shown when the hospital carries no address — the column is nullable. */
export const NO_ADDRESS = "Not recorded";

/**
 * What an administrator must be told about their hospital's verification, or null when
 * nothing is wrong.
 *
 * One sentence per state, in one place, so the dashboard and the My Hospital page cannot
 * drift into saying different things about the same hospital. The consequences named here
 * are the ones the backend actually enforces (ADR-015): `register_doctor` refuses a hospital
 * that is not VERIFIED, and so does every hospital upload.
 */
export const VERIFICATION_NOTICES: Readonly<Record<HospitalVerificationStatus, string | null>> = {
  VERIFIED: null,
  PENDING:
    "Your hospital is awaiting verification by a PulseOS system administrator. Until it is " +
    "verified, doctors cannot register to it and no records can be uploaded.",
};

const VERIFICATION_BADGES: Readonly<
  Record<HospitalVerificationStatus, { label: string; tone: Tone }>
> = {
  VERIFIED: { label: "Verified", tone: "success" },
  PENDING: { label: "Pending verification", tone: "warning" },
};

export interface HospitalIdentityView {
  hospitalName: string;
  /** The hospital's public identifier, `HID-XXXX` — what a doctor types to register. */
  hospitalHid: string;
  address: string;
  hasAddress: boolean;
  adminFullName: string;
  /** "12 Sep 2026" — when the hospital was registered on PulseOS. */
  registeredOn: string;
  verificationLabel: string;
  verificationTone: Tone;
  /** What to tell the administrator, or null when the state needs no explanation. */
  verificationNotice: string | null;
  /** ADR-015: only a VERIFIED hospital may take doctor registrations or upload records. */
  canOperate: boolean;
}

export function toIdentityView(profile: HospitalAdminProfile): HospitalIdentityView {
  const address = profile.hospital.address?.trim();
  const hasAddress = address !== undefined && address.length > 0;
  const badge = VERIFICATION_BADGES[profile.hospital.verificationStatus];
  return {
    hospitalName: profile.hospital.name,
    hospitalHid: profile.hospital.hid,
    address: hasAddress ? address : NO_ADDRESS,
    hasAddress,
    adminFullName: profile.adminFullName,
    registeredOn: formatInstantDate(profile.hospital.createdAt),
    verificationLabel: badge.label,
    verificationTone: badge.tone,
    verificationNotice: VERIFICATION_NOTICES[profile.hospital.verificationStatus],
    canOperate: profile.hospital.verificationStatus === "VERIFIED",
  };
}

/** First word of the administrator's name, for the greeting. */
export function firstNameOf(fullName: string): string {
  const [first] = fullName.trim().split(/\s+/);
  return first !== undefined && first.length > 0 ? first : "there";
}
