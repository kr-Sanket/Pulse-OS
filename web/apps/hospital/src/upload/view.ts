// Upload form rules and the wording around them. Pure functions, no React.
//
// The Health ID is no longer part of this draft. It belongs to patient-lookup/, because an
// upload may not proceed on a typed ID at all — only on a *confirmed patient*, which is a
// lookup result plus an explicit acknowledgement. Keeping the two apart is what makes
// "confirmed for patient A, uploaded for patient B" unrepresentable rather than merely
// unlikely.
//
// What is left here is what describes the document: the file, its category, when the care
// happened, and an optional description.

import { todayIsoDate } from "@pulseos/ui";

import type { PatientIdentity } from "@/patient-lookup/view";

import type { RecordMetadata } from "./api";

export type UploadField = "file" | "categoryCode" | "dateOfService";

/** What the administrator has chosen so far. `file` is null until one is picked. */
export interface UploadDraft {
  file: File | null;
  categoryCode: string | null;
  dateOfService: string;
  description: string;
}

export function emptyDraft(): UploadDraft {
  return {
    file: null,
    categoryCode: null,
    // Most uploads are same-day; the field is bounded above by today either way.
    dateOfService: todayIsoDate(),
    description: "",
  };
}

export const FIELD_LABELS: Readonly<Record<UploadField, string>> = {
  file: "Document",
  categoryCode: "Kind of document",
  dateOfService: "Date of service",
};

/** Why one field cannot be sent, or null when it can. */
export function fieldProblem(field: UploadField, draft: UploadDraft): string | null {
  switch (field) {
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

const FIELDS: readonly UploadField[] = ["file", "categoryCode", "dateOfService"];

/** Every field's problem, keyed by field — empty when the draft describes a sendable
 * document. Says nothing about *whose* document it is; see {@link uploadBlockedReason}. */
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

// -- the upload gate ---------------------------------------------------------------------
//
// Every condition that must hold before a document can be filed, in one place and in the
// order an administrator would hit them. Separate from the draft rules because most of these
// are not about the document at all: two are about the hospital, one is about the patient,
// and only the last is about the form.

export interface UploadGate {
  /** ADR-015: a PENDING hospital is refused by the API with 409. */
  hospitalCanOperate: boolean;
  /** The record-category vocabulary loaded; nothing can be categorised without it. */
  categoriesAvailable: boolean;
  /** A successful lookup that the administrator has explicitly confirmed. */
  patientConfirmed: boolean;
  draft: UploadDraft;
}

export const PENDING_HOSPITAL_BLOCKED =
  "Your hospital is not verified yet, so it cannot upload records.";
export const CATEGORIES_BLOCKED =
  "Record categories could not be loaded, so uploads are unavailable right now.";
export const PATIENT_NOT_CONFIRMED =
  "Find the patient by their Pulse Health ID and confirm their name before uploading.";
export const DRAFT_INCOMPLETE = "Complete the document details before uploading.";

/** Why this upload cannot proceed, or null when it can. First blocker wins, so the
 * administrator is told the one thing to do next rather than everything at once. */
export function uploadBlockedReason(gate: UploadGate): string | null {
  if (!gate.hospitalCanOperate) {
    return PENDING_HOSPITAL_BLOCKED;
  }
  if (!gate.categoriesAvailable) {
    return CATEGORIES_BLOCKED;
  }
  if (!gate.patientConfirmed) {
    return PATIENT_NOT_CONFIRMED;
  }
  return isSendable(gate.draft) ? null : DRAFT_INCOMPLETE;
}

export function canUpload(gate: UploadGate): boolean {
  return uploadBlockedReason(gate) === null;
}

// -- the receipt -------------------------------------------------------------------------

/** What the receipt shows after a successful upload. */
export interface ReceiptView {
  recordId: string;
  patientHealthId: string;
  /** The confirmed patient's name, so the operator can verify what they filed and for whom.
   * Taken from the lookup this upload was authorised by, never from the upload response —
   * `POST /records` returns no patient, and widening it for display would put a name on a
   * response that has never needed one. */
  patientName: string;
  category: string;
  dateOfService: string;
  filename: string;
  size: string;
  uploadedTo: string;
}

export const UNKNOWN_HOSPITAL = "Your hospital";

export function toReceiptView(
  record: RecordMetadata,
  patient: PatientIdentity,
  formatDate: (iso: string) => string,
  formatSize: (bytes: number) => string,
): ReceiptView {
  return {
    recordId: record.id,
    patientHealthId: patient.healthId,
    patientName: patient.fullName,
    category: record.categoryDisplayName,
    dateOfService: formatDate(record.dateOfService),
    filename: record.originalFilename,
    size: formatSize(record.sizeBytes),
    uploadedTo: record.uploadedByHospital?.name ?? UNKNOWN_HOSPITAL,
  };
}
