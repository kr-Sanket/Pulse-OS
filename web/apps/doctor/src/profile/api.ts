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
 * A 403 can also be a Firebase ID token minted before registration provisioned the
 * PulseOS claims. The caller refreshes that token once and this loader retries before
 * classifying the account as unregistered. That matters after a browser refresh too:
 * Firebase persists its cached token across page loads.
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
  refreshToken?: () => Promise<void>,
): Promise<ApiResult<ClinicianIdentity>> {
  return attempt<ClinicianIdentity>(async () => {
    let result = await client.GET("/api/v1/doctors/me", { signal });
    // Registration sets custom claims server-side. A normal getIdToken() may still return
    // the pre-registration token, including after a browser reload. Refresh only after the
    // expected unprovisioned response, then let the API make the authorization decision again.
    if (result.data === undefined && result.response.status === 403 && refreshToken !== undefined) {
      await refreshToken();
      result = await client.GET("/api/v1/doctors/me", { signal });
    }
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
