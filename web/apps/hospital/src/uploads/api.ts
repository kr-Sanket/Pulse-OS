// The records this hospital uploaded (GET /api/v1/records), plus the two calls that open
// one of them.
//
// Scope is decided entirely by the server: for a HOSPITAL_ADMIN, `GET /records` returns the
// records their hospital uploaded and nothing else (ADR-013 layer 2 — a hospital may read
// what it uploaded, and needs the patient's consent for everything else). No query narrows
// it to this hospital because none is needed, and none could widen it either.
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. This is the only file in the feature
// that touches the generated client.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type RecordMetadata = components["schemas"]["RecordMetadataResponse"];
export type RecordPage = components["schemas"]["RecordListResponse"];
export type DownloadUrl = components["schemas"]["DownloadUrlResponse"];

/** Asked for on every page: the API caps a page at 100 and this slice has no pager yet.
 * `nextCursor` is still read, so the UI can admit the limit rather than hide it. */
export const MAX_PAGE_SIZE = 100;

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your uploads.",
  403: "This account cannot list records.",
  404: "No hospital is attached to this account yet.",
  422: "That page of uploads could not be loaded.",
};

/**
 * The 404 wording is deliberately not a guess.
 *
 * A record outside the caller's reach answers 404, never 403 (docs/API_GUIDELINES.md). For
 * a hospital admin the reach is "records my hospital uploaded", so one status covers both
 * "no such record" and "that record is another hospital's". Naming one would confirm the
 * other exists, so the message names neither.
 */
const NOT_YOURS = "This record is not one of your hospital's uploads, so it cannot be opened here.";

const READ_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "This account cannot read records.",
  404: NOT_YOURS,
};

const DOWNLOAD_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then download the file.",
  403: "This account cannot read records.",
  404: NOT_YOURS,
  503: "File storage is unavailable right now. Nothing was downloaded; try again shortly.",
};

/**
 * One page of this hospital's uploads, newest added first.
 *
 * `cursor` is accepted because the endpoint is paginated and the response carries
 * `nextCursor`; no screen passes one yet, and the page says so rather than pretending a
 * hundred records is everything.
 */
export async function listUploads(
  client: PulseOSClient,
  signal: AbortSignal,
  cursor?: string,
): Promise<ApiResult<RecordPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/records", {
      params: { query: { limit: MAX_PAGE_SIZE, ...(cursor === undefined ? {} : { cursor }) } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your uploads.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * One record's metadata.
 *
 * Fetched rather than reused from the row the listing already returned: this is the read
 * the backend authorizes and audits, so the detail page asks for it in its own right and
 * shows the refusal if the answer has changed.
 */
export async function getUpload(
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
 * unsay it, and cancelling on unmount would only hide a fact that is already recorded.
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
