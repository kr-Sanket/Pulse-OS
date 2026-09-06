// Upload form rules and the wording around them. Pure functions, no React.
//
// Two jobs: normalise and shape-check the Health ID before a round trip, and say what a
// draft is still missing. Everything a server decides — whether the ID belongs to a real
// patient, whether the file is an accepted type, whether the hospital may upload at all — is
// left to the server, and its answer is what the form shows.

import { todayIsoDate } from "@pulseos/ui";

import type { RecordMetadata } from "./api";

/** ADR-012 stores canonical uppercase; a reception desk types whatever it types. */
export function normalizeHealthId(input: string): string {
  return input.trim().toUpperCase();
}

/**
 * Format-only check: the prefix, a four-digit year, and seven characters of body plus
 * check character.
 *
 * Deliberately *not* the ISO 7064 check-character verification the backend performs — that
 * algorithm lives in one place (app/modules/patients/health_id.py) and a TypeScript copy
 * would be free to drift. This is the same rule the doctor portal applies, and it catches a
 * malformed ID before a round trip; the server remains the authority on whether an ID is
 * real, and answers 422 when it is not.
 */
const HEALTH_ID_SHAPE = /^PHI-IND-\d{4}-[0-9A-Z]{7}$/;

export function looksLikeHealthId(input: string): boolean {
  return HEALTH_ID_SHAPE.test(normalizeHealthId(input));
}

export const INVALID_HEALTH_ID =
  "That is not a Pulse Health ID. The format is PHI-IND-YYYY-XXXXXXC.";

/** The standing warning above the form.
 *
 * A hospital administrator cannot look a patient up before uploading — no endpoint lets them
 * — and there is no endpoint that edits or deletes a record afterwards. So the Health ID is
 * the only thing standing between a document and the wrong patient's history, and it is
 * worth one sentence saying so. */
export const HEALTH_ID_CAUTION =
  "The document is filed against this Health ID and cannot be edited or removed afterwards. " +
  "Read it back from the patient's card before uploading.";

export type UploadField = "patientHealthId" | "file" | "categoryCode" | "dateOfService";

/** What the administrator has typed so far. `file` is null until one is chosen. */
export interface UploadDraft {
  patientHealthId: string;
  file: File | null;
  categoryCode: string | null;
  dateOfService: string;
  description: string;
}

export function emptyDraft(): UploadDraft {
  return {
    patientHealthId: "",
    file: null,
    categoryCode: null,
    // Most uploads are same-day; the field is bounded above by today either way.
    dateOfService: todayIsoDate(),
    description: "",
  };
}

export const FIELD_LABELS: Readonly<Record<UploadField, string>> = {
  patientHealthId: "Pulse Health ID",
  file: "Document",
  categoryCode: "Kind of document",
  dateOfService: "Date of service",
};

/** Why one field cannot be sent, or null when it can. */
export function fieldProblem(field: UploadField, draft: UploadDraft): string | null {
  switch (field) {
    case "patientHealthId": {
      const value = normalizeHealthId(draft.patientHealthId);
      if (value.length === 0) {
        return `${FIELD_LABELS.patientHealthId} is required.`;
      }
      return looksLikeHealthId(value) ? null : INVALID_HEALTH_ID;
    }
    case "file":
      return draft.file === null ? "Choose a file to upload." : null;
    case "categoryCode":
      return draft.categoryCode === null ? "Choose what kind of document this is." : null;
    case "dateOfService": {
      if (draft.dateOfService.length === 0) {
        return `${FIELD_LABELS.dateOfService} is required.`;
      }
      // The API refuses a future service date outright; catching it here saves the round
      // trip and, more usefully, names the field.
      return draft.dateOfService > todayIsoDate()
        ? "Date of service cannot be in the future."
        : null;
    }
  }
}

const FIELDS: readonly UploadField[] = ["patientHealthId", "file", "categoryCode", "dateOfService"];

/** Every field's problem, keyed by field — empty when the draft is sendable. */
export function draftProblems(draft: UploadDraft): Readonly<Partial<Record<UploadField, string>>> {
  const problems: Partial<Record<UploadField, string>> = {};
  for (const field of FIELDS) {
    const problem = fieldProblem(field, draft);
    if (problem !== null) {
      problems[field] = problem;
    }
  }
  return problems;
}

export function isSendable(draft: UploadDraft): boolean {
  return Object.keys(draftProblems(draft)).length === 0;
}

/** What the receipt shows after a successful upload. */
export interface ReceiptView {
  recordId: string;
  patientHealthId: string;
  category: string;
  dateOfService: string;
  filename: string;
  size: string;
  uploadedTo: string;
}

export const UNKNOWN_HOSPITAL = "Your hospital";

export function toReceiptView(
  record: RecordMetadata,
  patientHealthId: string,
  formatDate: (iso: string) => string,
  formatSize: (bytes: number) => string,
): ReceiptView {
  return {
    recordId: record.id,
    patientHealthId,
    category: record.categoryDisplayName,
    dateOfService: formatDate(record.dateOfService),
    filename: record.originalFilename,
    size: formatSize(record.sizeBytes),
    uploadedTo: record.uploadedByHospital?.name ?? UNKNOWN_HOSPITAL,
  };
}
