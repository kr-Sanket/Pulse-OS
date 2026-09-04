// The clinician's own profile (GET /api/v1/doctors/me).
//
// Same contract as every feature api module in the portals: the client is injected,
// nothing throws, and lib/apiResult (shared) owns the result shape.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type DoctorProfile = components["schemas"]["DoctorProfileResponse"];
export type DoctorStatus = components["schemas"]["DoctorStatus"];

/**
 * Who the signed-in account is on PulseOS.
 *
 * "You have no clinician profile" is a legitimate answer to "who am I", not a failure — it
 * is the state every clinician starts in, and the portal routes it to onboarding rather
 * than to an error screen. Only genuine failures (expired session, server trouble, no
 * network) come back as errors.
 *
 * Both 403 and 404 map to `unregistered`, deliberately. 403 covers two cases the API does
 * not distinguish by status — no PulseOS claims at all, and claims naming another role —
 * and guessing between them from a message string would be brittle. Registration answers
 * the question authoritatively: an account already registered as something else is refused
 * with 409, and the form shows the API's own words.
 */
export type ClinicianIdentity =
  { kind: "registered"; profile: DoctorProfile } | { kind: "unregistered" };

/** 403 and 404 are handled above as `unregistered`, so they are absent here by design. */
const PROFILE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
};

/** The statuses that mean "this account simply has no clinician profile yet". */
const UNREGISTERED_STATUSES: ReadonlySet<number> = new Set([403, 404]);

export async function loadDoctorProfile(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<ClinicianIdentity>> {
  return attempt<ClinicianIdentity>(async () => {
    const result = await client.GET("/api/v1/doctors/me", { signal });
    if (result.data === undefined) {
      if (UNREGISTERED_STATUSES.has(result.response.status)) {
        return { status: "ready", data: { kind: "unregistered" } };
      }
      return statusFailure(
        result.error,
        result.response.status,
        PROFILE_FAILURES,
        "Could not load your clinician profile.",
      );
    }
    return { status: "ready", data: { kind: "registered", profile: result.data } };
  });
}
