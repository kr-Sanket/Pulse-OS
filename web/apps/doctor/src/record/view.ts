// Backend record metadata → what the detail page renders. Pure functions, no React.
//
// This module owns the doctor portal's record vocabulary: how an origin, an uploading
// hospital, a file type and a processing state are worded. The granted listing re-exports
// what it needs from here rather than keeping its own copy, so a card and the detail page
// it opens can never describe the same record differently.
//
// Nothing here derives a fact the API does not send. Every field below maps one response
// field to one string; where the response says nothing — a null description, a missing
// hospital — the UI says so plainly instead of filling the gap.

import { formatCalendarDate, formatFileSize, formatInstantDate } from "@pulseos/ui";

import type { Tone } from "@/components/shell/StatusBadge";

import type {
  RecordMetadata,
  RecordOrigin,
  RecordProcessingStatus,
  UploadingHospital,
} from "./api";

// -- record vocabulary, shared with the granted listing -------------------------------------

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

// -- the detail page's own formatting --------------------------------------------------------

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

interface StatusPresentation {
  label: string;
  tone: Tone;
}

/**
 * ADR-008's pipeline states.
 *
 * `UPLOADED` is the only one the backend writes today — the OCR and embedding worker lands
 * at M5 — so the wording says where the document is, not what has been done to it. Nothing
 * here implies a capability that does not exist yet.
 */
const PROCESSING_STATUSES: Readonly<Record<RecordProcessingStatus, StatusPresentation>> = {
  UPLOADED: { label: "Stored", tone: "neutral" },
  PROCESSING: { label: "Being processed", tone: "info" },
  INDEXED: { label: "Indexed", tone: "success" },
  FAILED: { label: "Processing failed", tone: "destructive" },
};

export function processingLabel(status: RecordProcessingStatus): string {
  return PROCESSING_STATUSES[status].label;
}

export function processingTone(status: RecordProcessingStatus): Tone {
  return PROCESSING_STATUSES[status].tone;
}

export interface RecordDetailView {
  /** The document's own name, and the page's heading. The API models no title. */
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
  processingTone: Tone;
}

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

// -- downloading ------------------------------------------------------------------------------

/** What the Download button is doing. `preparing` is what stops a second click from asking
 * the server for a second link — and from writing a second download to the patient's trail
 * for one intention. */
export type DownloadState =
  { kind: "idle" } | { kind: "preparing" } | { kind: "failed"; message: string };

export const DOWNLOAD_IDLE: DownloadState = { kind: "idle" };

/** Shown when the link was issued but the browser refused to follow it. The download has
 * already been audited at this point, so the message must not suggest nothing happened. */
export const POPUP_BLOCKED =
  "Your browser blocked the download window. Allow pop-ups for PulseOS and try again.";
