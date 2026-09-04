// The onboarding form's state: the draft, what is wrong with it, the one POST, and the
// profile that comes back.
//
// Named useDoctorRegistration rather than the brief's `hook.ts` to match the six feature
// folders already in the portals, every one of which names its hook after what it does.
//
// Not the shared useApiResource: that hook loads a resource when its inputs change, and this
// is a mutation the clinician performs once. What is shared is everything underneath — the
// client, the result contract and the error wording (register/api.ts).

import { useState } from "react";

import { api } from "@/api";

import { registerDoctor, type DoctorProfile, type DoctorRegistrationDraft } from "./api";
import { draftProblems, EMPTY_DRAFT, isSendable, type DraftField } from "./view";

export type RegistrationState =
  | { kind: "editing" }
  | { kind: "submitting" }
  /** The API accepted it; the profile exists and is PENDING until an administrator acts. */
  | { kind: "registered"; profile: DoctorProfile }
  | { kind: "error"; message: string };

export interface DoctorRegistration {
  draft: DoctorRegistrationDraft;
  setField: (field: DraftField, value: string) => void;
  /** Per-field problems, surfaced only once a submit has been attempted. */
  problems: Readonly<Partial<Record<DraftField, string>>>;
  /** True when every required field is filled and within its limit. */
  sendable: boolean;
  state: RegistrationState;
  submit: () => void;
}

export function useDoctorRegistration(): DoctorRegistration {
  const [draft, setDraft] = useState<DoctorRegistrationDraft>(EMPTY_DRAFT);
  const [state, setState] = useState<RegistrationState>({ kind: "editing" });
  // An untouched form should not scold; problems appear once the clinician has tried.
  const [attempted, setAttempted] = useState(false);

  async function send(): Promise<void> {
    setAttempted(true);
    if (!isSendable(draft)) {
      return;
    }
    setState({ kind: "submitting" });
    const result = await registerDoctor(api, draft);
    setState(
      result.status === "error"
        ? { kind: "error", message: result.message }
        : { kind: "registered", profile: result.data },
    );
  }

  return {
    draft,
    setField: (field, value) => {
      setDraft((current) => ({ ...current, [field]: value }));
      // A failed attempt is stale the moment the clinician edits; clear it so the form
      // is not left showing an error about text that no longer exists.
      setState((current) => (current.kind === "error" ? { kind: "editing" } : current));
    },
    problems: attempted ? draftProblems(draft) : {},
    sendable: isSendable(draft),
    state,
    submit: () => void send(),
  };
}
