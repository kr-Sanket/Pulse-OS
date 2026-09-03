// Every backend call the Medical Records page makes, in one place.
//
// Same shape as profile/loadProfile.ts: the client is injected, nothing throws, and every
// call answers with a discriminated result. No React here, so the whole module is
// unit-testable without a DOM.
//
// Requests carry the caller's AbortSignal. An aborted fetch rejects rather than resolving,
// so it lands in `attempt` below and comes back as an error result — the caller
// (useApiResource) discards results for signals it has already aborted, which is why
// nothing here needs to distinguish an abort from a genuine failure.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, failure, statusFailure, type ApiResult } from "@/lib/apiResult";

export type RecordMetadata = components["schemas"]["RecordMetadataResponse"];
export type RecordPage = components["schemas"]["RecordListResponse"];
export type DownloadUrl = components["schemas"]["DownloadUrlResponse"];

// The category vocabulary is shared with Consent and lives in lib/; re-exported here so
// this module stays the one place the Records page imports its API from.
export {
  categoryLabel,
  categoryLabels,
  listCategories,
  type RecordCategory,
} from "@/lib/recordCategories";
export type { ApiResult } from "@/lib/apiResult";

/** Asked for on every listing: the API caps a page at 100 and the page has no pager. */
const MAX_PAGE_SIZE = 100;

/** Per-status wording for an upload, used only when the API sends no problem detail. */
const UPLOAD_FAILURES: Readonly<Record<number, string>> = {
  403: "Your account is not allowed to upload records.",
  404: "Your patient profile is not set up yet.",
  413: "That file is larger than the upload limit.",
  415: "That file type is not accepted. Upload a PDF, JPEG or PNG.",
  422: "Check the category and date of service, then try again.",
  503: "Storage is unavailable right now — nothing was uploaded.",
};

/** The caller's own records, newest first. `categoryCode` null means every category. */
export async function listRecords(
  client: PulseOSClient,
  categoryCode: string | null,
  signal: AbortSignal,
): Promise<ApiResult<RecordPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/records", {
      params: { query: { category: categoryCode ?? undefined, limit: MAX_PAGE_SIZE } },
      signal,
    });
    if (result.data === undefined) {
      return failure(result.error, "Could not load your records.");
    }
    return { status: "ready", data: result.data };
  });
}

/** One record's metadata. This is the read the backend audits, so the panel re-fetches
 * rather than reusing the row the listing already returned. */
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
      return failure(result.error, "Could not load this record.");
    }
    return { status: "ready", data: result.data };
  });
}

/** A short-lived presigned URL for the record's file. Audited as a download, not a view. */
export async function createDownloadUrl(
  client: PulseOSClient,
  recordId: string,
): Promise<ApiResult<DownloadUrl>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/records/{record_id}/download-url", {
      params: { path: { record_id: recordId } },
    });
    if (result.data === undefined) {
      return failure(result.error, "Could not prepare the download.");
    }
    return { status: "ready", data: result.data };
  });
}

export interface RecordUpload {
  file: File;
  categoryCode: string;
  /** ISO calendar date (yyyy-mm-dd), as the date input produces it. */
  dateOfService: string;
  description: string | null;
}

/** Multipart, not JSON: openapi-fetch hands the body to this serializer instead. */
export function toFormData(body: unknown): FormData {
  const form = new FormData();
  for (const [field, value] of Object.entries(body as Record<string, unknown>)) {
    if (value === null || value === undefined) {
      continue;
    }
    form.append(field, value instanceof Blob ? value : String(value));
  }
  return form;
}

/** Upload one document to the patient's own locker. `patientHealthId` is deliberately
 * absent — the API rejects it on locker uploads and takes the patient from the token. */
export async function uploadRecord(
  client: PulseOSClient,
  upload: RecordUpload,
): Promise<ApiResult<RecordMetadata>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/records", {
      body: {
        categoryCode: upload.categoryCode,
        dateOfService: upload.dateOfService,
        description: upload.description,
        // openapi-typescript types a binary form field as `string`; toFormData puts the
        // real File on the FormData, so no string is ever sent for it.
        file: upload.file as unknown as string,
      },
      bodySerializer: toFormData,
    });
    if (result.data === undefined) {
      return statusFailure(result.error, result.response.status, UPLOAD_FAILURES, "Upload failed.");
    }
    return { status: "ready", data: result.data };
  });
}
