// Backend record metadata → what the detail page renders.
//
// The record vocabulary itself — how an origin, an uploading hospital, a file type and a
// processing state are worded, and the mapping from a record response to a detail view —
// now lives in @pulseos/ui, because the hospital portal reads the same
// `RecordMetadataResponse` and a document described two different ways by two PulseOS
// screens would be a defect rather than a nuance.
//
// What stays here is this portal's own wording: the 404 sentence is in api.ts, and the
// re-exports below are what the feature's components, its tests and the granted listing
// import, so neither has to know where a name came from.

export {
  descriptionOf,
  fileTypeLabel,
  hospitalLabel,
  NO_DESCRIPTION,
  originLabel,
  PATIENT_UPLOADED,
  processingLabel,
  processingTone,
  toRecordDetailView,
  UNKNOWN_HOSPITAL,
  type RecordDetailView,
} from "@pulseos/ui";

export { DOWNLOAD_IDLE, POPUP_BLOCKED, type DownloadState } from "@pulseos/ui";
