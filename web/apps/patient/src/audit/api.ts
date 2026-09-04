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

/** Asked for on the listing: the API caps a page at 100 and the page has no pager. */
export const MAX_PAGE_SIZE = 100;

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your history.",
  403: "This account cannot view this audit trail.",
  404: "Your patient profile is not set up yet.",
  422: "That page of history could not be loaded.",
};

/** The patient's own trail, most recent event first. */
export async function listAuditEvents(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<AuditEventPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/audit-logs", {
      params: { query: { limit: MAX_PAGE_SIZE } },
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
