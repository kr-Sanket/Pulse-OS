// One request, four states, plus a manual reload — the whole async story this page needs.
//
// Hand-rolled rather than pulled from a data library on purpose: ADR-003 stops at a typed
// client, the portal holds no global state, and the alternative is the same effect written
// out three times on one page. A null loader means "nothing to fetch yet" (no record is
// selected), which keeps the caller free of conditional hooks.
//
// Lives in the shared package rather than in one app: every portal loads pages this way,
// and a second copy of an abort-and-reload effect is exactly the duplication this file
// exists to prevent (ADR-003).

import { useEffect, useState } from "react";

import type { ApiResult } from "./apiResult";

export type Resource<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

/** The signal aborts the request when the inputs change or the page unmounts. */
export type Loader<T> = (signal: AbortSignal) => Promise<ApiResult<T>>;

export interface ApiResourceState<T> {
  resource: Resource<T>;
  /** Re-runs the current loader — used to retry, and after an upload changes the list. */
  reload: () => void;
}

export function useApiResource<T>(load: Loader<T> | null): ApiResourceState<T> {
  const [resource, setResource] = useState<Resource<T>>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (load === null) {
      setResource({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setResource({ status: "loading" });
    void load(controller.signal).then((result) => {
      // A superseded request always loses: its signal is already aborted.
      if (controller.signal.aborted) {
        return;
      }
      setResource(
        result.status === "ready"
          ? { status: "ready", data: result.data }
          : { status: "error", message: result.message },
      );
    });
    return () => controller.abort();
  }, [load, attempt]);

  return { resource, reload: () => setAttempt((count) => count + 1) };
}
