// The Audit History page's state: an accumulating, cursor-paginated trail.
//
// **Not the shared useApiResource, and this is the first screen in the project that cannot
// use it.** That hook holds one response and replaces it when the inputs change; this page
// has to keep every page it has loaded and append the next. Every other listing in the
// portals asks for a hundred rows and admits the truncation in a footnote — a compliance
// view is the first place where "and the rest is not shown" is not good enough.
//
// Kept local rather than promoted: one screen needs it, and a pagination hook designed
// against a single caller would be a guess at what the second one wants.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api";

import { listHospitalAuditEvents, type HospitalAuditEvent } from "./api";
import { appendPage, toAuditEventViews, type AuditEventView } from "./view";

export interface HospitalAuditTrail {
  /** Every row loaded so far, in the server's order. */
  items: readonly AuditEventView[];
  /** The first page is in flight and there is nothing to show yet. */
  isLoading: boolean;
  /** A further page is in flight; what is already on screen stays. */
  isLoadingMore: boolean;
  /** Why the last request failed, or null. */
  error: string | null;
  hasMore: boolean;
  /** No-op while a request is already running, or when there is no next page. */
  loadMore: () => void;
  /** Re-run from the beginning, discarding what was loaded. */
  retry: () => void;
}

export function useAudit(): HospitalAuditTrail {
  const [events, setEvents] = useState<readonly HospitalAuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // The guard is a ref, not the `busy` state, so a second click in the same tick cannot
  // slip past a value that only settles on the next render — the same reasoning the record
  // download guard uses, and here it would mean a page appended twice.
  const inFlight = useRef(false);

  const load = useCallback(async (next: string | undefined, replace: boolean) => {
    if (inFlight.current) {
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);

    const controller = new AbortController();
    const result = await listHospitalAuditEvents(api, controller.signal, next);

    inFlight.current = false;
    setBusy(false);
    setLoaded(true);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    setEvents((current) => (replace ? result.data.items : appendPage(current, result.data.items)));
    setCursor(result.data.nextCursor);
  }, []);

  // First page on arrival, and again whenever the reader retries.
  useEffect(() => {
    void load(undefined, true);
  }, [load, attempt]);

  const isFirstLoad = !loaded && events.length === 0;

  return {
    items: toAuditEventViews(events),
    isLoading: isFirstLoad && error === null,
    isLoadingMore: busy && !isFirstLoad,
    error,
    // No next page, and never while one is loading — the control disappears rather than
    // offering an action that would be ignored.
    hasMore: cursor !== null && !busy,
    loadMore: () => {
      if (cursor !== null) {
        void load(cursor, false);
      }
    },
    retry: () => {
      setEvents([]);
      setCursor(null);
      setLoaded(false);
      setAttempt((count) => count + 1);
    },
  };
}
