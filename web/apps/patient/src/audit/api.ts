// Every backend call the Audit History page makes — one, for now.
//
// Same contract as the other feature api modules: the client is injected, nothing throws,
// every call answers with a discriminated result, and lib/apiResult.ts owns the shape.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type AuditEvent = components["schemas"]["AuditEventResponse"];
export type AuditEventPage = components["schemas"]["AuditEventListResponse"];
export type AuditAction = components["schemas"]["AuditAction"];
export type ActorRole = components["schemas"]["Role"];
export type Actor = components["schemas"]["StaffDisplayResponse"];
/** The organisation an event was attributed to *when it was written* (ADR-025). Not the
 * actor's current employer — that is `Actor.hospitalName`, and it answers a different
 * question. Null for the patient's own actions and for events predating attribution. */
export type AuditHospital = components["schemas"]["AuditHospitalResponse"];

/** One page of the trail. Small enough to render grouped without a wall of rows, and the
 * page has a Load more, so it is a page size rather than the cap it used to be. */
export const AUDIT_PAGE_SIZE = 25;

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your history.",
  403: "This account cannot view this audit trail.",
  404: "Your patient profile is not set up yet.",
  422: "That page of history could not be loaded.",
};

/**
 * The patient's own trail, most recent event first.
 *
 * `cursor` continues the previous page. The endpoint has always been cursor-paginated; the
 * page simply never used it, which capped the trail at its first page and — once the events
 * are grouped — would have made a collapsed group look complete when it was not.
 */
export async function listAuditEvents(
  client: PulseOSClient,
  signal: AbortSignal,
  cursor?: string,
): Promise<ApiResult<AuditEventPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/audit-logs", {
      params: { query: { limit: AUDIT_PAGE_SIZE, cursor } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your audit history.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
