// Hospital + administrator onboarding (POST /api/v1/hospitals/register, ADR-015 step 1).
//
// Same contract as every feature api module — injected client, nothing thrown, the shared
// result shape from @pulseos/ui. One call: registration is idempotent server-side, so there
// is nothing to update and nothing to retry differently.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type HospitalAdminProfile = components["schemas"]["HospitalAdminProfileResponse"];

/** The API's own field limits, mirrored so the form can stop a doomed request before the
 * round trip. The same numbers, not a second rule — the server remains the authority. */
export const MAX_HOSPITAL_NAME_LENGTH = 120;
export const MAX_HOSPITAL_ADDRESS_LENGTH = 255;
export const MAX_ADMIN_FULL_NAME_LENGTH = 120;

/** Used only where the API sends no problem detail of its own. */
const REGISTER_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then submit these details.",
  409: "This account is already registered on PulseOS under a different role.",
  422: "Check the details you entered, then try again.",
  503: "PulseOS could not complete your registration just now. Nothing was saved; try again.",
};

export interface HospitalRegistrationDraft {
  hospitalName: string;
  /** Optional on the API; empty means "not recorded". */
  hospitalAddress: string;
  adminFullName: string;
}

/**
 * Register a new hospital with the signed-in account as its administrator.
 *
 * The hospital always starts PENDING and is given a random `HID-XXXX` by the server — a
 * PulseOS system administrator verifies it. Idempotent: a repeat call answers 200 with the
 * existing hospital rather than creating a second one, which is why a double submission is
 * harmless.
 *
 * `hospitalAddress` is sent as null when blank: the column is nullable, and an empty string
 * would record "the address is the empty string" rather than "no address was given".
 */
export async function registerHospital(
  client: PulseOSClient,
  draft: HospitalRegistrationDraft,
): Promise<ApiResult<HospitalAdminProfile>> {
  return attempt(async () => {
    const address = draft.hospitalAddress.trim();
    const result = await client.POST("/api/v1/hospitals/register", {
      body: {
        hospitalName: draft.hospitalName.trim(),
        hospitalAddress: address.length === 0 ? null : address,
        adminFullName: draft.adminFullName.trim(),
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
