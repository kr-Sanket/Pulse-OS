// The medical-record vocabulary every portal shares: how an origin, an uploading hospital,
// a file type and a processing state are worded, and the one mapping from the record
// response to the fields a detail screen renders.
//
// Shared rather than per portal because a record does not change meaning with the reader.
// The doctor portal reads records a patient consented to share; the hospital portal reads
// records it uploaded itself. Both are looking at the same `RecordMetadataResponse`, and a
// document described two different ways by two PulseOS screens would be a defect, not a
// nuance — which is why this file exists instead of a second copy of it.
//
// Nothing here derives a fact the API does not send. Every function maps one response field
// to one string; where the response says nothing — a null description, a missing hospital —
// the caller is told so plainly rather than having the gap filled.

import type { components } from "@pulseos/api-client";

import { formatCalendarDate, formatInstantDate } from "./dates";
import { formatFileSize } from "./fileSize";

export type RecordMetadata = components["schemas"]["RecordMetadataResponse"];
export type RecordOrigin = components["schemas"]["RecordOrigin"];
export type RecordProcessingStatus = components["schemas"]["RecordProcessingStatus"];
export type UploadingHospital = components["schemas"]["UploadingHospitalResponse"];
export type DownloadUrl = components["schemas"]["DownloadUrlResponse"];

/** The tone vocabulary each portal's StatusBadge accepts. Declared here so a shared mapping
 * can name a tone without importing an app's component. */
export type StatusTone = "success" | "warning" | "info" | "destructive" | "neutral" | "primary";

const ORIGIN_LABELS: Readonly<Record<RecordOrigin, string>> = {
  HOSPITAL_UPLOAD: "Hospital upload",
  PATIENT_LOCKER: "Patient locker",
};

/** Who brought the record onto PulseOS — a trust signal, not provenance trivia: a
 * hospital-issued report and a photograph the patient uploaded warrant different weight. */
export function originLabel(origin: RecordOrigin): string {
  return ORIGIN_LABELS[origin];
}

/** A locker record has no uploading hospital, and saying so is more honest than a dash. */
export const PATIENT_UPLOADED = "Added by the patient";
/** A hospital upload whose hospital no longer resolves — never blank, never invented. */
export const UNKNOWN_HOSPITAL = "Hospital not identified";

export function hospitalLabel(hospital: UploadingHospital | null, origin: RecordOrigin): string {
  if (hospital !== null) {
    return hospital.name;
  }
  return origin === "PATIENT_LOCKER" ? PATIENT_UPLOADED : UNKNOWN_HOSPITAL;
}

/** Shown where the uploader recorded no description. The field is nullable and often null;
 * an empty line would read as a rendering fault. */
export const NO_DESCRIPTION = "No description was recorded for this document.";

export function descriptionOf(record: RecordMetadata): string | null {
  const description = record.description?.trim();
  return description === undefined || description.length === 0 ? null : description;
}

/** The three formats the upload path accepts, as a reader would name them. Anything else is
 * shown verbatim — a MIME type is ugly but true, and a wrong guess is worse. */
const FILE_TYPE_LABELS: Readonly<Record<string, string>> = {
  "application/pdf": "PDF",
  "image/jpeg": "JPEG image",
  "image/png": "PNG image",
};

export function fileTypeLabel(contentType: string): string {
  return FILE_TYPE_LABELS[contentType] ?? contentType;
}

/**
 * ADR-008's pipeline states.
 *
 * `UPLOADED` is the only one the backend writes today — the OCR and embedding worker lands
 * at M5 — so the wording says where the document is, not what has been done to it. Nothing
 * here implies a capability that does not exist yet.
 */
const PROCESSING_STATUSES: Readonly<
  Record<RecordProcessingStatus, { label: string; tone: StatusTone }>
> = {
  UPLOADED: { label: "Stored", tone: "neutral" },
  PROCESSING: { label: "Being processed", tone: "info" },
  INDEXED: { label: "Indexed", tone: "success" },
  FAILED: { label: "Processing failed", tone: "destructive" },
};

export function processingLabel(status: RecordProcessingStatus): string {
  return PROCESSING_STATUSES[status].label;
}

export function processingTone(status: RecordProcessingStatus): StatusTone {
  return PROCESSING_STATUSES[status].tone;
}

export interface RecordDetailView {
  /** The document's own name, and a detail page's heading. The API models no title. */
  fileName: string;
  categoryCode: string;
  categoryName: string;
  /** "1 Mar 2026" — when the care happened. Formatted in UTC; it is a calendar date. */
  dateOfService: string;
  /** Null when the uploader recorded none — the card omits the row rather than filling it. */
  description: string | null;
  origin: string;
  hospital: string;
  /** "4 Sep 2026" — when it reached PulseOS, which is rarely the same day. */
  uploadedOn: string;
  /** "2.4 MB". */
  fileSize: string;
  /** "PDF". */
  fileType: string;
  processingLabel: string;
  processingTone: StatusTone;
}

/** The whole of a record response, worded. The two date formats are not interchangeable:
 * `dateOfService` is a zoneless calendar date and `createdAt` is an instant, so formatting
 * them the same way would slip the service date a day for readers west of Greenwich. */
export function toRecordDetailView(record: RecordMetadata): RecordDetailView {
  return {
    fileName: record.originalFilename,
    categoryCode: record.categoryCode,
    categoryName: record.categoryDisplayName,
    dateOfService: formatCalendarDate(record.dateOfService),
    description: descriptionOf(record),
    origin: originLabel(record.origin),
    hospital: hospitalLabel(record.uploadedByHospital, record.origin),
    uploadedOn: formatInstantDate(record.createdAt),
    fileSize: formatFileSize(record.sizeBytes),
    fileType: fileTypeLabel(record.contentType),
    processingLabel: processingLabel(record.processingStatus),
    processingTone: processingTone(record.processingStatus),
  };
}
