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

import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiResult } from "./apiResult";

export type Resource<T> =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; message: string };

/** The signal aborts the request when the inputs change or the page unmounts. */
export type Loader<T> = (signal: AbortSignal) => Promise<ApiResult<T>>;

export interface AutoRefreshOptions {
  /** Periodic polling interval in milliseconds while the component is mounted. Set to null/undefined or <= 0 to disable. */
  pollIntervalMs?: number | null;
  /** Whether to re-trigger a background refresh when the browser tab regains focus or becomes visible. Defaults to true when pollIntervalMs is configured. */
  refreshOnFocus?: boolean;
}

export interface ApiResourceState<T> {
  resource: Resource<T>;
  /** Re-runs the current loader — used to retry, and after a mutation changes data. */
  reload: () => void;
  /** Silent background refresh — fetches fresh data without resetting state to 'loading' if already 'ready'. */
  refresh: () => void;
}

export function useApiResource<T>(
  load: Loader<T> | null,
  options?: AutoRefreshOptions,
): ApiResourceState<T> {
  const [resource, setResource] = useState<Resource<T>>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);

  const loaderRef = useRef<Loader<T> | null>(load);
  loaderRef.current = load;

  const inFlightRef = useRef(false);
  const activeControllerRef = useRef<AbortController | null>(null);

  const pollIntervalMs = options?.pollIntervalMs ?? null;
  const refreshOnFocus = options?.refreshOnFocus ?? (pollIntervalMs !== null && pollIntervalMs > 0);

  // Core execution function: handles both initial/explicit load (showing loading) and silent background refresh
  const execute = useCallback(async (isSilentRefresh = false) => {
    const currentLoader = loaderRef.current;
    if (currentLoader === null) {
      setResource({ status: "idle" });
      return;
    }

    if (inFlightRef.current) {
      return;
    }

    inFlightRef.current = true;

    // Abort any previous pending request
    activeControllerRef.current?.abort();
    const controller = new AbortController();
    activeControllerRef.current = controller;

    if (!isSilentRefresh) {
      setResource({ status: "loading" });
    }

    try {
      const result = await currentLoader(controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      setResource(
        result.status === "ready"
          ? { status: "ready", data: result.data }
          : { status: "error", message: result.message },
      );
    } catch (err: unknown) {
      if (controller.signal.aborted) {
        return;
      }
      // Never crash on network/aborted errors; fallback to error state
      const message = err instanceof Error ? err.message : "Failed to load resource";
      setResource({ status: "error", message });
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  // Main loader effect: runs when `load` or manual `attempt` counter changes
  useEffect(() => {
    void execute(false);
    return () => {
      activeControllerRef.current?.abort();
      inFlightRef.current = false;
    };
  }, [load, attempt, execute]);

  // Periodic polling and tab focus / visibility refresh lifecycle
  useEffect(() => {
    if (load === null) {
      return;
    }

    let intervalId: ReturnType<typeof setInterval> | null = null;
    if (pollIntervalMs !== null && pollIntervalMs > 0) {
      intervalId = setInterval(() => {
        void execute(true);
      }, pollIntervalMs);
    }

    const onFocus = () => {
      if (refreshOnFocus) {
        void execute(true);
      }
    };

    const onVisibilityChange = () => {
      if (
        refreshOnFocus &&
        typeof document !== "undefined" &&
        document.visibilityState === "visible"
      ) {
        void execute(true);
      }
    };

    if (refreshOnFocus) {
      if (typeof window !== "undefined") {
        window.addEventListener("focus", onFocus);
      }
      if (typeof document !== "undefined") {
        document.addEventListener("visibilitychange", onVisibilityChange);
      }
    }

    return () => {
      if (intervalId !== null) {
        clearInterval(intervalId);
      }
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", onFocus);
      }
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
  }, [load, pollIntervalMs, refreshOnFocus, execute]);

  const reload = useCallback(() => setAttempt((count) => count + 1), []);
  const refresh = useCallback(() => void execute(true), [execute]);

  return { resource, reload, refresh };
}
