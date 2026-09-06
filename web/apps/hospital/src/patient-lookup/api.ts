// Confirming which patient a Pulse Health ID identifies (GET /api/v1/patients/lookup).
//
// The safety step in front of an upload: a record is filed against a Health ID and no
// endpoint can move or delete it afterwards, so the uploader has to be able to check whose
// history they are about to write to.
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. This is the only file in the feature
// that touches the generated client.
//
// **This confirms an identity; it authorizes nothing.** The upload that follows is
// authorized independently by the records module, which re-resolves the Health ID itself
// and still requires a VERIFIED hospital. Nothing here may be treated as permission.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

/** Two fields, and deliberately no more: the Health ID in canonical form and the name to
 * read back to the person at the desk. The API sends nothing else. */
export type PatientIdentity = components["schemas"]["PatientLookupResponse"];

/** The API's own bound on the field. A Health ID is exactly this long, so a padded value is
 * refused at the boundary — the caller normalises before sending. */
export const MAX_HEALTH_ID_LENGTH = 20;

/**
 * Used only where the API sends no problem detail of its own.
 *
 * 422 covers two answers the backend states apart in its detail — a malformed ID and a
 * well-formed one nobody holds — so the API's own sentence is preferred and this is only
 * the floor. ADR-012's check character is what makes the distinction possible offline, and
 * it is worth keeping: "you typed it wrong" and "this person is not on PulseOS" are
 * different instructions to whoever is at the desk.
 */
const LOOKUP_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then look the patient up.",
  403: "This account cannot look patients up.",
  422: "That Pulse Health ID does not match a patient.",
};

export async function lookupPatient(
  client: PulseOSClient,
  healthId: string,
  signal: AbortSignal,
): Promise<ApiResult<PatientIdentity>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/patients/lookup", {
      params: { query: { healthId } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LOOKUP_FAILURES,
        "Could not look this patient up.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
