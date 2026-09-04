// The Request Access flow: which categories are selected, the dialog, the purpose, and the
// one POST that turns them into a pending request.
//
// Everything the screens need to decide lives here; RequestAccessDialog and CategoryResults
// render what this returns and report events back. The validation rules themselves are pure
// functions in view.ts, so they are unit-tested without a DOM and the hook stays short.
//
// Not the shared useApiResource: that hook loads a resource when its inputs change, and this
// is a mutation a clinician performs. What is shared is everything underneath — the client,
// the result contract and the error wording (requests/api.ts).

import { useMemo, useState } from "react";

import { api } from "@/api";

import { createAccessRequest, type CreatedAccessRequest } from "./api";
import { draftProblem, selectionProblem } from "./view";

export type SubmitState =
  | { kind: "idle" }
  | { kind: "submitting" }
  /** The API accepted it; the request is PENDING until the patient answers. */
  | { kind: "sent"; request: CreatedAccessRequest }
  | { kind: "error"; message: string };

export interface AccessRequestFlow {
  /** Category codes the clinician has ticked. */
  selected: ReadonlySet<string>;
  toggleCategory: (code: string) => void;
  clearSelection: () => void;
  /** True when the selection alone would be accepted — drives the Request Access button. */
  canRequest: boolean;
  dialogOpen: boolean;
  /** Opens the dialog on a clean draft. No-op while the selection is unusable. */
  openDialog: () => void;
  /** Cancel or dismiss. Ignored while a submission is in flight. */
  setDialogOpen: (open: boolean) => void;
  purpose: string;
  setPurpose: (purpose: string) => void;
  /** Why the draft cannot be sent yet, or null. Shown only after a submit attempt. */
  problem: string | null;
  state: SubmitState;
  submit: (patientHealthId: string) => void;
  /** Dismiss the success confirmation: closes the dialog and clears the draft. */
  finish: () => void;
  /** Full reset — used when a new patient is searched. */
  reset: () => void;
}

export function useAccessRequest(): AccessRequestFlow {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [purpose, setPurpose] = useState("");
  const [state, setState] = useState<SubmitState>({ kind: "idle" });
  // Only surfaced once the clinician has tried to send; an empty form should not scold.
  const [attempted, setAttempted] = useState(false);

  const codes = useMemo(() => [...selected], [selected]);
  const canRequest = selectionProblem(codes) === null;

  function toggleCategory(code: string): void {
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(code)) {
        next.add(code);
      }
      return next;
    });
  }

  function clearDraft(): void {
    setPurpose("");
    setState({ kind: "idle" });
    setAttempted(false);
  }

  async function send(patientHealthId: string): Promise<void> {
    setAttempted(true);
    if (draftProblem(codes, purpose) !== null) {
      return;
    }
    setState({ kind: "submitting" });
    const result = await createAccessRequest(api, {
      patientHealthId,
      categoryCodes: codes,
      purpose: purpose.trim(),
    });
    setState(
      result.status === "error"
        ? { kind: "error", message: result.message }
        : { kind: "sent", request: result.data },
    );
  }

  return {
    selected,
    toggleCategory,
    clearSelection: () => setSelected(new Set()),
    canRequest,
    dialogOpen,
    openDialog: () => {
      if (!canRequest) {
        return;
      }
      clearDraft();
      setDialogOpen(true);
    },
    setDialogOpen: (open) => {
      // A submission in flight cannot be cancelled, so the dialog stays put until it settles.
      if (state.kind === "submitting") {
        return;
      }
      setDialogOpen(open);
      if (!open) {
        clearDraft();
      }
    },
    purpose,
    setPurpose,
    problem: attempted ? draftProblem(codes, purpose) : null,
    state,
    submit: (patientHealthId) => void send(patientHealthId),
    finish: () => {
      setDialogOpen(false);
      setSelected(new Set());
      clearDraft();
    },
    reset: () => {
      setSelected(new Set());
      setDialogOpen(false);
      clearDraft();
    },
  };
}
