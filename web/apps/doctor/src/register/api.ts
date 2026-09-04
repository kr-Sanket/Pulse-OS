// Clinician self-registration (POST /api/v1/doctors/register, ADR-015 step 3).
//
// Same contract as every feature api module — injected client, nothing thrown, the shared
// result shape from @pulseos/ui. One call: registration is idempotent server-side, so there
// is nothing to update and nothing to retry differently.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type DoctorProfile = components["schemas"]["DoctorProfileResponse"];

/** The API's own field limits, mirrored so the form can stop a doomed request before the
 * round trip. The same numbers, not a second rule — the server remains the authority. */
export const MAX_FULL_NAME_LENGTH = 120;
export const MAX_REGISTRATION_NUMBER_LENGTH = 40;
export const MAX_SPECIALTY_LENGTH = 80;
export const MAX_HOSPITAL_HID_LENGTH = 8;

/** Used only where the API sends no problem detail of its own. */
const REGISTER_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then submit your details.",
  409: "This account is already registered, or that hospital cannot take registrations yet.",
  422: "Check your details — that hospital ID may not exist.",
  503: "PulseOS could not complete your registration just now. Nothing was saved; try again.",
};

export interface DoctorRegistrationDraft {
  fullName: string;
  registrationNumber: string;
  /** Optional on the API; empty means "not recorded". */
  specialty: string;
  /** `HID-XXXX`, as printed on the hospital's PulseOS record. */
  hospitalHid: string;
}

/**
 * Register the signed-in account as a clinician of a verified hospital.
 *
 * The profile always starts PENDING — a hospital administrator activates it. Idempotent:
 * a repeat call answers 200 with the existing profile rather than creating a second one,
 * which is why a double submission is harmless.
 *
 * `specialty` is sent as null when blank: the column is nullable, and an empty string would
 * record "the specialty is the empty string" rather than "no specialty was given".
 */
export async function registerDoctor(
  client: PulseOSClient,
  draft: DoctorRegistrationDraft,
): Promise<ApiResult<DoctorProfile>> {
  return attempt(async () => {
    const specialty = draft.specialty.trim();
    const result = await client.POST("/api/v1/doctors/register", {
      body: {
        fullName: draft.fullName.trim(),
        registrationNumber: draft.registrationNumber.trim(),
        specialty: specialty.length === 0 ? null : specialty,
        hospitalHid: draft.hospitalHid.trim().toUpperCase(),
      },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        REGISTER_FAILURES,
        "Could not complete your registration.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
