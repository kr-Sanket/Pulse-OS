// The lookup panel's state: one Health ID, one search at a time, and the confirmation.
//
// Not the shared useApiResource: that hook loads a resource when its inputs change, and a
// lookup runs when an administrator presses a button. The states differ too — "nothing
// looked up yet" is not "loading". What is shared is everything underneath: the client, the
// result contract and the error wording.
//
// Every transition goes through patient-lookup/view.ts, so the rule that matters — a
// confirmation dies with the Health ID that earned it — is enforced in one tested place
// rather than across four setState calls.
//
// Local to the upload workflow by design. There is no patient store, and the name is never
// held anywhere beyond this hook's own state.

import { useState } from "react";

import { api } from "@/api";

import { lookupPatient } from "./api";
import {
  canSearch,
  confirmedPatient,
  IDLE_SESSION,
  startSearch,
  withConfirmation,
  withError,
  withHealthId,
  withResult,
  type LookupSession,
  type PatientIdentity,
} from "./view";

export interface PatientLookup {
  session: LookupSession;
  /** Editing the Health ID clears any result and confirmation for the previous one. */
  setHealthId: (raw: string) => void;
  /** No-op unless the ID looks plausible and no search is already running. */
  find: () => void;
  setConfirmed: (confirmed: boolean) => void;
  /** The patient an upload may proceed against, or null. */
  patient: PatientIdentity | null;
  searchable: boolean;
  /** Clear everything — used when the form is reset for the next patient. */
  reset: () => void;
}

export function usePatientLookup(): PatientLookup {
  const [session, setSession] = useState<LookupSession>(IDLE_SESSION);

  async function run(current: LookupSession): Promise<void> {
    const healthId =
      current.state.kind === "searching" ? current.healthId.trim().toUpperCase() : "";
    const controller = new AbortController();
    const result = await lookupPatient(api, healthId, controller.signal);
    setSession((latest) => {
      // The administrator may have retyped while the request was in flight; a result for a
      // Health ID they have moved on from must not land on the one they are looking at now.
      if (latest.healthId.trim().toUpperCase() !== healthId) {
        return latest;
      }
      return result.status === "error"
        ? withError(latest, result.message)
        : withResult(latest, result.data);
    });
  }

  return {
    session,
    setHealthId: (raw) => setSession((current) => withHealthId(current, raw)),
    find: () =>
      setSession((current) => {
        if (!canSearch(current)) {
          return current;
        }
        const searching = startSearch(current);
        void run(searching);
        return searching;
      }),
    setConfirmed: (confirmed) => setSession((current) => withConfirmation(current, confirmed)),
    patient: confirmedPatient(session),
    searchable: canSearch(session),
    reset: () => setSession(IDLE_SESSION),
  };
}
