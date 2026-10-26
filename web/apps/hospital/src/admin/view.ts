// Presentation mappings, types, and validation for System Admin Hospital Verification.
//
// Pure functions, no React, so all view rules can be unit tested without a DOM.

import type { Tone } from "@/components/shell/StatusBadge";
import type { Hospital, HospitalLifecycleAction, HospitalVerificationStatus } from "./api";

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
  REJECTED: { label: "Rejected", tone: "destructive" },
  SUSPENDED: { label: "Suspended", tone: "neutral" },
};

export const LIFECYCLE_ACTION_CONFIG: Readonly<
  Record<HospitalLifecycleAction, { label: string; tone: Tone }>
> = {
  VERIFIED: { label: "Verified", tone: "success" },
  REJECTED: { label: "Rejected", tone: "destructive" },
  SUSPENDED: { label: "Suspended", tone: "warning" },
  REINSTATED: { label: "Reinstated", tone: "primary" },
};

export type VerificationFilter = "ALL" | "PENDING" | "VERIFIED" | "SUSPENDED" | "REJECTED";

export const FILTER_OPTIONS: readonly { id: VerificationFilter; label: string }[] = [
  { id: "ALL", label: "All Hospitals" },
  { id: "PENDING", label: "Pending Verification" },
  { id: "VERIFIED", label: "Verified" },
  { id: "SUSPENDED", label: "Suspended" },
  { id: "REJECTED", label: "Rejected" },
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

export type HistoryPanelState = "loading" | "error" | "empty" | "list";

/**
 * Which body the lifecycle audit-history panel shows (ADR-034). An error always wins over
 * stale or empty data, so a failed load is never presented as "no events recorded".
 */
export function historyPanelState(
  loading: boolean,
  error: string | null,
  logs: readonly unknown[] | null,
): HistoryPanelState {
  if (error !== null) return "error";
  if (loading || logs === null) return "loading";
  return logs.length === 0 ? "empty" : "list";
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
