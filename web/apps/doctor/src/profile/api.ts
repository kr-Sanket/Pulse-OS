// The clinician's own profile (GET /api/v1/doctors/me).
//
// Same contract as every feature api module in the portals: the client is injected,
// nothing throws, and lib/apiResult (shared) owns the result shape.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type DoctorProfile = components["schemas"]["DoctorProfileResponse"];
export type DoctorStatus = components["schemas"]["DoctorStatus"];

const PROFILE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "This account is not registered as a clinician.",
  404: "No clinician profile is attached to this account yet.",
};

export async function loadDoctorProfile(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<DoctorProfile>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/doctors/me", { signal });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        PROFILE_FAILURES,
        "Could not load your clinician profile.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
