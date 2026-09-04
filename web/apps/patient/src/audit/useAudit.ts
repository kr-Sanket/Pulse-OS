// The Audit History page's state: the trail and the category vocabulary that renders it.
//
// Read-only, unlike the consent and grants pages — an audit log has no actions to take on
// it — so this is the shared useApiResource twice over plus the mapping in view.ts. It
// exists so the page reads as declaratively as the others and so the summary is computed in
// exactly one place.

import { useCallback, useMemo } from "react";

import { api } from "@/api";
import { categoryLabels, listCategories } from "@/lib/recordCategories";
import { useApiResource } from "@pulseos/ui";

import { listAuditEvents, MAX_PAGE_SIZE } from "./api";
import { summarize, toEventViews, type AuditEventView, type SummaryStat } from "./view";

export interface AuditTrail {
  status: "loading" | "ready" | "error";
  /** Why the trail failed to load, when it did. */
  message: string | null;
  events: readonly AuditEventView[];
  /** Figures over the loaded page only — the API has no aggregate endpoint. */
  summary: readonly SummaryStat[];
  /** True when the API has more events than one page holds. */
  truncated: boolean;
  /** How many events a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useAudit(): AuditTrail {
  const loadTrail = useCallback((signal: AbortSignal) => listAuditEvents(api, signal), []);
  const trail = useApiResource(loadTrail);

  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const trailResource = trail.resource;
  const vocabularyResource = vocabulary.resource;

  const labels = useMemo(
    () =>
      vocabularyResource.status === "ready"
        ? categoryLabels(vocabularyResource.data)
        : new Map<string, string>(),
    [vocabularyResource],
  );

  const entries = trailResource.status === "ready" ? trailResource.data.items : [];
  // Recomputed per render on purpose: "2 hours ago" is read from the clock, and a page of
  // this size costs nothing to map.
  const events = toEventViews(entries, labels);

  return {
    status: trailResource.status === "idle" ? "loading" : trailResource.status,
    message: trailResource.status === "error" ? trailResource.message : null,
    events,
    summary: summarize(entries, events),
    truncated: trailResource.status === "ready" && trailResource.data.nextCursor !== null,
    pageSize: MAX_PAGE_SIZE,
    reload: trail.reload,
  };
}
