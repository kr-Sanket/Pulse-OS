// One granted record: its metadata, and a short-lived link to its file.
//
// GET /api/v1/records/{record_id} and POST /api/v1/records/{record_id}/download-url — the
// two calls that actually cross the enforcement choke point. The listing that led here was
// a filter; these are the reads. Each one is authorized on its own and written to the
// patient's audit trail, and the second is recorded as a download rather than a view, so
// taking a file is distinguishable from looking at its details.
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. This is the only file in the feature
// that touches the generated client.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type RecordMetadata = components["schemas"]["RecordMetadataResponse"];
export type DownloadUrl = components["schemas"]["DownloadUrlResponse"];
export type RecordOrigin = components["schemas"]["RecordOrigin"];
export type RecordProcessingStatus = components["schemas"]["RecordProcessingStatus"];
export type UploadingHospital = components["schemas"]["UploadingHospitalResponse"];

/**
 * The 404 wording carries the weight here, and it is deliberately not a guess.
 *
 * A record outside the caller's reach answers 404, never 403 (docs/API_GUIDELINES.md), so
 * one status covers "no such record", "the patient revoked your grant", "the grant expired"
 * and "the patient hid the document" — the API refuses to distinguish them, because saying
 * which would confirm the record exists. The message therefore names the likely causes
 * without claiming one, and never tells a clinician the record is gone when the truth may
 * be that their access is.
 */
const NO_LONGER_AVAILABLE =
  "This record is not available to you. The patient may have withdrawn your access, the " +
  "grant may have expired, or the document may have been hidden.";

const READ_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "Your clinician profile is not active at its hospital.",
  404: NO_LONGER_AVAILABLE,
};

const DOWNLOAD_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then download the file.",
  403: "Your clinician profile is not active at its hospital.",
  404: NO_LONGER_AVAILABLE,
  503: "File storage is unavailable right now. Nothing was downloaded; try again shortly.",
};

/**
 * One record's metadata.
 *
 * The read the backend audits, so the page fetches it rather than reusing the row the
 * granted listing already returned: a grant revoked between the two refuses here, which is
 * exactly the behaviour that makes an id from a listing safe to hold.
 */
export async function getRecord(
  client: PulseOSClient,
  recordId: string,
  signal: AbortSignal,
): Promise<ApiResult<RecordMetadata>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/records/{record_id}", {
      params: { path: { record_id: recordId } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        READ_FAILURES,
        "Could not load this record.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * A short-lived presigned URL for the record's file.
 *
 * Carries no AbortSignal on purpose: this is a write in audit terms — the server records a
 * download the moment it issues the link — so abandoning the request client-side would not
 * unsay it, and cancelling on unmount would only hide a fact the patient can already see.
 */
export async function createDownloadUrl(
  client: PulseOSClient,
  recordId: string,
): Promise<ApiResult<DownloadUrl>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/records/{record_id}/download-url", {
      params: { path: { record_id: recordId } },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        DOWNLOAD_FAILURES,
        "Could not prepare the download.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
