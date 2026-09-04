// The granted-records screen's state: one patient's consented listing, and its outcome.
//
// The shared useApiResource does the work — one request, aborted and re-run when the
// patient changes, with a manual reload for the error state. What this adds is the outcome
// derivation, so neither the page nor the search screen has to know that an empty `items`
// means two different things depending on the scope beside it.
//
// A null Health ID means "nothing to load yet", which is what lets the search page mount
// this hook unconditionally and still fetch nothing until a patient has been found.

import { useMemo } from "react";

import { useApiResource } from "@pulseos/ui";

import { api } from "@/api";

import { listGrantedRecords, MAX_PAGE_SIZE } from "./api";
import { outcomeFor, type GrantedRecordsOutcome } from "./view";

export interface GrantedRecordsResource {
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  /** What to render, or null until a response has landed. */
  outcome: GrantedRecordsOutcome | null;
  /** How many records a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useGrantedRecords(patientHealthId: string | null): GrantedRecordsResource {
  // The loader is the null, rather than a loader guarded by one: that way the Health ID is
  // narrowed by the closure and never needs a cast, and useApiResource sees "nothing to
  // fetch" as the single condition it already understands.
  const load = useMemo(
    () =>
      patientHealthId === null
        ? null
        : (signal: AbortSignal) => listGrantedRecords(api, patientHealthId, signal),
    [patientHealthId],
  );
  const { resource, reload } = useApiResource(load);

  return {
    // "Nothing requested yet" reads as loading to a page that only mounts with a patient,
    // and the search screen ignores the status and looks at the outcome instead.
    status: resource.status === "idle" ? "loading" : resource.status,
    message: resource.status === "error" ? resource.message : null,
    outcome: resource.status === "ready" ? outcomeFor(resource.data) : null,
    pageSize: MAX_PAGE_SIZE,
    reload,
  };
}
