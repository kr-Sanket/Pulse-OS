// Uploading one document against a patient's Pulse Health ID (POST /api/v1/records,
// multipart) — the hospital half of the endpoint the patient portal uses for its locker.
//
// Same contract as every feature api module — injected client, nothing thrown, the shared
// result shape from @pulseos/ui. The multipart serialiser is shared too (@pulseos/ui
// `toFormData`), because both callers send the same shape to the same route.
//
// `patientHealthId` is what makes this the hospital path: the API requires it from a
// HOSPITAL_ADMIN and refuses it on a locker upload, so the two flows cannot be confused.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, toFormData, type ApiResult } from "@pulseos/ui";

export type RecordMetadata = components["schemas"]["RecordMetadataResponse"];

/** Mirrors ALLOWED_CONTENT_TYPES in the records service — a file-picker hint, not a check.
 * The server re-validates and answers 415, which is what gets shown when it refuses. */
export const ACCEPTED_TYPES = "application/pdf,image/jpeg,image/png";

/** The API's own limit on the free-text description. */
export const MAX_DESCRIPTION_LENGTH = 255;

/** The API's own limit on the Health ID field. */
export const MAX_HEALTH_ID_LENGTH = 20;

/** Used only where the API sends no problem detail of its own.
 *
 * The upload path has the widest failure set in the portal, and three of these are states a
 * receptionist can actually be in, so each says what to do rather than what went wrong. */
const UPLOAD_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then upload this document.",
  403: "This account is not allowed to upload records.",
  404: "No hospital is attached to this account yet.",
  409: "Your hospital is not verified yet, so it cannot upload records.",
  413: "That file is larger than the upload limit.",
  415: "That file type is not accepted. Upload a PDF, JPEG or PNG.",
  422: "Check the Pulse Health ID, the category and the date of service, then try again.",
  503: "Storage is unavailable right now — nothing was uploaded.",
};

export interface HospitalRecordUpload {
  /** Canonical uppercase; the API trims and uppercases too. */
  patientHealthId: string;
  file: File;
  categoryCode: string;
  /** ISO calendar date (yyyy-mm-dd), as the date input produces it. */
  dateOfService: string;
  description: string | null;
}

/**
 * Upload one document for the patient holding this Health ID.
 *
 * Requires a VERIFIED hospital (ADR-015) — an unverified one is refused with 409. The record
 * belongs to the *patient*, not to the hospital: uploading it grants this hospital a
 * standing right to read back what it uploaded and nothing else, and gives the hospital no
 * access to anything else the patient holds.
 *
 * There is no endpoint that edits or deletes a record afterwards, so a successful upload is
 * final — which is why the form makes the administrator confirm the Health ID first.
 */
export async function uploadRecordForHealthId(
  client: PulseOSClient,
  upload: HospitalRecordUpload,
): Promise<ApiResult<RecordMetadata>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/records", {
      body: {
        patientHealthId: upload.patientHealthId,
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
      return statusFailure(
        result.error,
        result.response.status,
        UPLOAD_FAILURES,
        "Could not upload this document.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
