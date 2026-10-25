// The administrator's own hospital (GET /api/v1/hospitals/me).
//
// Same contract as every feature api module in the portals: the client is injected,
// nothing throws, and lib/apiResult (shared) owns the result shape.

import type { components, PulseOSClient } from "@pulseos/api-client";
import {
  ACCOUNT_SUSPENDED_MESSAGE,
  attempt,
  isAccountSuspended,
  statusFailure,
  type ApiResult,
} from "@pulseos/ui";

export type HospitalAdminProfile = components["schemas"]["HospitalAdminProfileResponse"];
export type HospitalVerificationStatus = components["schemas"]["HospitalVerificationStatus"];

/**
 * Who the signed-in account is on PulseOS.
 *
 * "You administer no hospital" is a legitimate answer to "who am I", not a failure — it is
 * the state every administrator starts in, and the portal routes it to onboarding rather
 * than to an error screen. Only genuine failures (expired session, server trouble, no
 * network) come back as errors.
 *
 * Both 403 and 404 map to `unregistered`, deliberately. 403 covers two cases the API does
 * not distinguish by status — no PulseOS claims at all, and claims naming another role —
 * and guessing between them from a message string would be brittle. Registration answers
 * the question authoritatively: an account already registered as something else is refused
 * with 409, and the form shows the API's own words.
 */
export type HospitalIdentity =
  { kind: "registered"; profile: HospitalAdminProfile } | { kind: "unregistered" };

/** 403 and 404 are handled above (`unregistered`, or suspended), so they are absent here by
 * design. */
const PROFILE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
};

/** The statuses that mean "this account simply administers no hospital yet". */
const UNREGISTERED_STATUSES: ReadonlySet<number> = new Set([403, 404]);

export async function loadHospitalProfile(
  client: PulseOSClient,
  signal: AbortSignal,
  refreshToken?: () => Promise<void>,
): Promise<ApiResult<HospitalIdentity>> {
  return attempt<HospitalIdentity>(async () => {
    let result = await client.GET("/api/v1/hospitals/me", { signal });
    // A suspended account is a 403 too, but not an unprovisioned one: refreshing the token
    // cannot help and onboarding would be refused, so it is reported, never routed.
    if (result.data === undefined && isAccountSuspended(result.response.status, result.error)) {
      return { status: "error", message: ACCOUNT_SUSPENDED_MESSAGE };
    }
    // Registration sets custom claims server-side. A normal getIdToken() may still return
    // the pre-registration token, including after a browser reload. Refresh only after the
    // expected unprovisioned response, then let the API make the authorization decision again.
    if (result.data === undefined && result.response.status === 403 && refreshToken !== undefined) {
      await refreshToken();
      result = await client.GET("/api/v1/hospitals/me", { signal });
    }
    if (result.data === undefined) {
      if (isAccountSuspended(result.response.status, result.error)) {
        return { status: "error", message: ACCOUNT_SUSPENDED_MESSAGE };
      }
      if (UNREGISTERED_STATUSES.has(result.response.status)) {
        return { status: "ready", data: { kind: "unregistered" } };
      }
      return statusFailure(
        result.error,
        result.response.status,
        PROFILE_FAILURES,
        "Could not load your hospital.",
      );
    }
    return { status: "ready", data: { kind: "registered", profile: result.data } };
  });
}
