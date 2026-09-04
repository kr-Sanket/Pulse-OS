// The clinician's consented view of one patient (GET /api/v1/granted-records, ADR-020).
//
// The step that turns an approval into something a doctor can open: until this endpoint
// existed a clinician could hold a live grant and still not name a single record, because
// ids are random and no listing admitted them.
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. No React here, so the whole module is
// unit-testable without a DOM. This is the only file in the feature that touches the
// generated client.
//
// **The listing permits nothing.** It is filtered by the categories consent reports as
// granted; every record opened from it still passes `consent.enforce` one at a time, so an
// id taken from this page stops working the moment its grant is revoked. Nothing here
// should ever be treated as permission.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

/** One record as its grantee may see it before opening it: enough to choose, and nothing
 * that describes the document. Filename, description, size, content type and processing
 * status are not on this response at all — they are disclosed by the single authorized
 * read, which is a later slice. */
export type GrantedRecord = components["schemas"]["GrantedRecordResponse"];
export type GrantedRecordPage = components["schemas"]["GrantedRecordListResponse"];
export type RecordOrigin = components["schemas"]["RecordOrigin"];
export type UploadingHospital = components["schemas"]["UploadingHospitalResponse"];

/** Asked for on every page: the API caps a page at 100 and this slice has no pager yet.
 * `nextCursor` is still read, so the UI can admit the limit rather than hide it. */
export const MAX_PAGE_SIZE = 100;

/**
 * Used only where the API sends no problem detail of its own.
 *
 * There is deliberately no wording for "no grant": that is a 200 with an empty scope, not a
 * failure. A clinician who has not been given anything is told so by the page, not by an
 * error — they already know the patient exists, having searched the Health ID.
 */
const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "Your clinician profile is not active at its hospital.",
  404: "No clinician profile is attached to this account yet.",
  422: "No patient matches that Pulse Health ID.",
};

/**
 * The records this clinician's grants currently cover for one patient, newest first.
 *
 * `cursor` is accepted because the endpoint is paginated and the response carries
 * `nextCursor`; no screen passes one yet, and the page says so rather than pretending a
 * hundred records is everything.
 */
export async function listGrantedRecords(
  client: PulseOSClient,
  patientHealthId: string,
  signal: AbortSignal,
  cursor?: string,
): Promise<ApiResult<GrantedRecordPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/granted-records", {
      params: {
        query: {
          patientHealthId,
          limit: MAX_PAGE_SIZE,
          ...(cursor === undefined ? {} : { cursor }),
        },
      },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load the records you have been granted.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
