// Presentation mappings, types, and validation for System Admin Hospital Verification.
//
// Pure functions, no React, so all view rules can be unit tested without a DOM.

import type { Tone } from "@/components/shell/StatusBadge";
import type { Hospital, HospitalVerificationStatus } from "./api";

export interface HospitalReviewItem {
  hid: string;
  name: string;
  address: string | null;
  status: HospitalVerificationStatus;
  verifiedAt?: string | null;
  verifiedByUserId?: string | null;
}

export const VERIFICATION_STATUS_CONFIG: Readonly<
  Record<HospitalVerificationStatus, { label: string; tone: Tone }>
> = {
  PENDING: { label: "Pending Verification", tone: "warning" },
  VERIFIED: { label: "Verified", tone: "success" },
};

export type VerificationFilter = "ALL" | "PENDING" | "VERIFIED";

export const FILTER_OPTIONS: readonly { id: VerificationFilter; label: string }[] = [
  { id: "ALL", label: "All Hospitals" },
  { id: "PENDING", label: "Pending Verification" },
  { id: "VERIFIED", label: "Verified" },
];

export function toReviewItemFromResponse(hospital: Hospital): HospitalReviewItem {
  return {
    hid: hospital.hid,
    name: hospital.name,
    address: hospital.address ?? null,
    status: hospital.verificationStatus,
    verifiedAt: hospital.verifiedAt ?? null,
    verifiedByUserId: hospital.verifiedByUserId ?? null,
  };
}

/**
 * Shortens a verifier UUID for compact display (first 8 characters).
 */
export function formatVerifierId(userId: string | null | undefined): string | null {
  if (!userId) return null;
  return userId.slice(0, 8);
}

/**
 * Validates a Hospital ID (HID) format.
 * Expects HID-XXXX format.
 */
export function validateHospitalId(rawHid: string): string | null {
  const trimmed = rawHid.trim().toUpperCase();
  if (!trimmed) {
    return "Hospital ID (HID) is required.";
  }
  if (!/^HID-[A-Z0-9]{4,6}$/.test(trimmed)) {
    return "Hospital ID must match the format 'HID-XXXX' (e.g. HID-0001).";
  }
  return null;
}
