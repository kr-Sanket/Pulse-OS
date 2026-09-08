// The Personal Information card's edit state.
//
// Everything decidable without React lives in view.ts — the draft shape, dirty tracking,
// validation and the partial diff — so this file holds only what React has to: the current
// draft, whether a save is in flight, and which errors are on screen.
//
// The hook does not own the profile. It reports a saved one upward through `onSaved`, so
// the page's single source of truth stays useProfile's state and the two can never disagree
// about what the server currently holds.

import { useCallback, useState } from "react";

import { api } from "@/api";

import { updateProfile, type PatientProfile } from "./api";
import {
  changedFields,
  draftFrom,
  fieldForWireName,
  isDirty,
  validateDraft,
  type EditableField,
  type FieldErrors,
  type ProfileDraft,
} from "./view";

export interface ProfileEditor {
  editing: boolean;
  draft: ProfileDraft;
  /** True when Save would send something. Save is disabled otherwise. */
  dirty: boolean;
  saving: boolean;
  fieldErrors: FieldErrors;
  /** A failure that belongs to no single field: network, 401/403/404, or an unmapped 422. */
  formError: string | null;
  /** Set after a successful save, cleared as soon as editing resumes. */
  saved: boolean;
  begin: () => void;
  cancel: () => void;
  change: (field: EditableField, value: string) => void;
  save: () => void;
}

export function useProfileEditor(
  profile: PatientProfile,
  onSaved: (updated: PatientProfile) => void,
): ProfileEditor {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<ProfileDraft>(() => draftFrom(profile));
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const begin = useCallback(() => {
    // Always re-seed from the server's copy: the profile may have been reloaded since the
    // last edit, and an editor opening on a stale draft would silently re-apply old values.
    setDraft(draftFrom(profile));
    setFieldErrors({});
    setFormError(null);
    setSaved(false);
    setEditing(true);
  }, [profile]);

  const cancel = useCallback(() => {
    setDraft(draftFrom(profile));
    setFieldErrors({});
    setFormError(null);
    setEditing(false);
  }, [profile]);

  const change = useCallback((field: EditableField, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
    // Clear only this field's error: the others are still true until re-validated on save,
    // and blanking them all would make a form look valid while it is not.
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    setFormError(null);
  }, []);

  const save = useCallback(() => {
    if (saving) {
      return; // duplicate-submit guard: a second click while in flight does nothing
    }
    const invalid = validateDraft(draft);
    if (Object.values(invalid).some((message) => message !== undefined)) {
      setFieldErrors(invalid);
      return;
    }
    const update = changedFields(profile, draft);
    if (Object.keys(update).length === 0) {
      setEditing(false); // nothing changed; the API would refuse an empty body anyway
      return;
    }
    setSaving(true);
    setFieldErrors({});
    setFormError(null);
    void updateProfile(api, update).then((result) => {
      setSaving(false);
      if (result.status === "error") {
        setFormError(result.message);
        return;
      }
      onSaved(result.data);
      setDraft(draftFrom(result.data));
      setEditing(false);
      setSaved(true);
    });
  }, [draft, onSaved, profile, saving]);

  return {
    editing,
    draft,
    dirty: isDirty(profile, draft),
    saving,
    fieldErrors,
    formError,
    saved,
    begin,
    cancel,
    change,
    save,
  };
}

/** Exported for the tests that pin the 422→field mapping without a DOM. */
export { fieldForWireName };
