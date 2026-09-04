// The record-existence projection (GET /api/v1/records/existence).
//
// The only backend call the patient-search slice makes. Same contract as every feature api
// module: injected client, nothing thrown, shared result shape.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type RecordCategory = components["schemas"]["RecordCategoryResponse"];
export type RecordExistence = components["schemas"]["RecordExistenceResponse"];

/**
 * Used only where the API sends no problem detail of its own.
 *
 * 422 is the interesting one: the API answers it both for a malformed Health ID and for a
 * well-formed one that matches no patient, and it does not distinguish them — deliberately,
 * because confirming which Health IDs exist is the oracle the backend is trying not to be.
 * The wording therefore covers both without guessing.
 */
const SEARCH_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "Your clinician profile is not active at its hospital.",
  404: "No clinician profile is attached to this account yet.",
  422: "No patient matches that Pulse Health ID.",
};

export async function searchRecordExistence(
  client: PulseOSClient,
  patientHealthId: string,
  signal: AbortSignal,
): Promise<ApiResult<RecordExistence>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/records/existence", {
      params: { query: { patientHealthId } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        SEARCH_FAILURES,
        "Could not search for this patient.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
