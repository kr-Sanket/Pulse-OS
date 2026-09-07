// This hospital's own audit activity (GET /api/v1/hospitals/me/audit-logs, ADR-023).
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. This is the only file in the feature
// that touches the generated client.
//
// **The response is the whole truth and there is nothing to enrich it with.** The endpoint
// deliberately withholds the patient, the hospital, the tamper digest and every clinical
// fact; this module must not fetch any of them back. A record id is the only identifier it
// carries, and looking that record up to decorate a row would re-disclose exactly what the
// allow-list exists to withhold — and would write a `RECORD_VIEWED` event per row while
// doing it.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type HospitalAuditEvent = components["schemas"]["HospitalAuditEventResponse"];
export type HospitalAuditPage = components["schemas"]["HospitalAuditEventListResponse"];
export type AuditAction = components["schemas"]["AuditAction"];
export type ActorRole = components["schemas"]["Role"];

/** How many events a page holds.
 *
 * Smaller than the API's 100 cap, and smaller than every other listing in the portals,
 * because this is the first screen with a real pager: a page has to be short enough that
 * "Load more" means something. The server remains the authority on the cap.
 */
export const PAGE_SIZE = 25;

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your audit history.",
  403: "This account cannot view your hospital's audit history.",
  404: "No hospital administrator profile is attached to this account.",
  // The UI never builds a cursor itself — it only ever echoes one the API returned — so
  // this is a "something is out of step" message rather than an instruction.
  422: "That page of audit history could not be loaded. Reload to start again.",
};

/**
 * One page of this hospital's activity, most recent event first.
 *
 * `cursor` is the opaque value the previous page returned; nothing here constructs one.
 * The scope is the caller's own hospital, decided server-side from their admin profile —
 * there is no hospital parameter to send, and no way for this client to ask for another
 * hospital's history.
 */
export async function listHospitalAuditEvents(
  client: PulseOSClient,
  signal: AbortSignal,
  cursor?: string,
): Promise<ApiResult<HospitalAuditPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/hospitals/me/audit-logs", {
      params: { query: { limit: PAGE_SIZE, ...(cursor === undefined ? {} : { cursor }) } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your hospital's audit history.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
