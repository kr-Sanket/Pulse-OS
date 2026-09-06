// The upload form's state: the draft, what is wrong with it, the one POST, and the record
// that comes back.
//
// Not the shared useApiResource: that hook loads a resource when its inputs change, and this
// is a mutation an administrator performs deliberately. What is shared is everything
// underneath — the client, the result contract and the error wording (upload/api.ts).
//
// The category vocabulary IS a load, so it goes through the shared hook.

import { useCallback, useState } from "react";

import { listCategories, useApiResource, type RecordCategory } from "@pulseos/ui";

import { api } from "@/api";

import type { PatientIdentity } from "@/patient-lookup/view";

import { uploadRecordForHealthId, type RecordMetadata } from "./api";
import { draftProblems, emptyDraft, isSendable, type UploadDraft, type UploadField } from "./view";

export type UploadState =
  | { kind: "editing" }
  | { kind: "uploading" }
  /** The API created the record; `patient` is the confirmed identity it was filed against,
   * carried through so the receipt can name them without the upload response doing so. */
  | { kind: "uploaded"; record: RecordMetadata; patient: PatientIdentity }
  | { kind: "error"; message: string };

export interface RecordUpload {
  draft: UploadDraft;
  setField: <K extends keyof UploadDraft>(field: K, value: UploadDraft[K]) => void;
  /** Per-field problems, surfaced only once a submit has been attempted. */
  problems: Readonly<Partial<Record<UploadField, string>>>;
  sendable: boolean;
  state: UploadState;
  /** Files the document against the confirmed patient. The identity is passed in rather
   * than held here: this hook must not be able to upload for anyone the lookup has not
   * confirmed, and taking it as an argument is what makes that structural. */
  submit: (patient: PatientIdentity) => void;
  /** Clear the form for the next patient, keeping nothing from the last one. */
  reset: () => void;
  /** The record categories to choose from, empty until they load. */
  categories: readonly RecordCategory[];
  /** True when the vocabulary could not be loaded, so no upload can be categorised. */
  categoriesUnavailable: boolean;
}

export function useRecordUpload(): RecordUpload {
  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const [draft, setDraft] = useState<UploadDraft>(emptyDraft);
  const [state, setState] = useState<UploadState>({ kind: "editing" });
  // An untouched form should not scold; problems appear once the administrator has tried.
  const [attempted, setAttempted] = useState(false);

  const vocabularyResource = vocabulary.resource;
  const categories = vocabularyResource.status === "ready" ? vocabularyResource.data : [];

  async function send(patient: PatientIdentity): Promise<void> {
    setAttempted(true);
    if (!isSendable(draft) || draft.file === null || draft.categoryCode === null) {
      return;
    }
    setState({ kind: "uploading" });

    const description = draft.description.trim();
    const result = await uploadRecordForHealthId(api, {
      // The canonical ID the *server* returned from the lookup, not the typed one.
      patientHealthId: patient.healthId,
      file: draft.file,
      categoryCode: draft.categoryCode,
      dateOfService: draft.dateOfService,
      // The column is nullable; "" would record that the description *is* the empty string.
      description: description.length === 0 ? null : description,
    });

    setState(
      result.status === "error"
        ? { kind: "error", message: result.message }
        : { kind: "uploaded", record: result.data, patient },
    );
  }

  function reset(): void {
    setDraft(emptyDraft());
    setState({ kind: "editing" });
    setAttempted(false);
  }

  return {
    draft,
    setField: (field, value) => {
      setDraft((current) => ({ ...current, [field]: value }));
      // A failed attempt is stale the moment the administrator edits; clear it so the form
      // is not left showing an error about a draft that no longer exists.
      setState((current) => (current.kind === "error" ? { kind: "editing" } : current));
    },
    problems: attempted ? draftProblems(draft) : {},
    sendable: isSendable(draft),
    state,
    submit: (patient) => void send(patient),
    reset,
    categories,
    categoriesUnavailable: vocabularyResource.status === "error",
  };
}
