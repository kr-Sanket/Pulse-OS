// The Audit History page's state: the trail, the category vocabulary that renders it, and
// which of the two views the reader has asked for.
//
// Read-only, unlike the consent and grants pages — an audit log has no actions to take on
// it — so this is the shared useApiResource twice over plus the mapping in view.ts. It
// exists so the page reads as declaratively as the others and so the summary is computed in
// exactly one place.
//
// The "show my activity" switch lives here rather than on the page for one reason: the
// timeline and the summary must never describe different sets of events. Both are derived
// from a single filtered list, so a figure that disagreed with the rows beneath it is not
// expressible. The request is unaffected — one page is fetched and every row is kept in
// memory, so flipping the switch is instant and costs nothing.

import { useCallback, useMemo, useState } from "react";

import { api } from "@/api";
import { categoryLabels, listCategories } from "@pulseos/ui";
import { useApiResource } from "@pulseos/ui";

import { listAuditEvents, MAX_PAGE_SIZE } from "./api";
import {
  countOwnRecordAccess,
  filterAuditEntries,
  summarizeAuditEntries,
  toEventViews,
  type AuditEventView,
  type SummaryStat,
} from "./view";

export interface AuditTrail {
  status: "loading" | "ready" | "error";
  /** Why the trail failed to load, when it did. */
  message: string | null;
  /** The rows to render: the whole page, or everyone else's activity on it. */
  events: readonly AuditEventView[];
  /** Figures over the visible rows only — the API has no aggregate endpoint. */
  summary: readonly SummaryStat[];
  /** False by default: the page answers "who else touched my records?" first. */
  showOwnActivity: boolean;
  setShowOwnActivity: (show: boolean) => void;
  /** How many of the patient's own reads the default view is holding back. Zero means the
   * timeline is empty because nothing happened, not because something was filtered. */
  hiddenOwnActivity: number;
  /** True when the API has more events than one page holds. */
  truncated: boolean;
  /** How many events a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useAudit(): AuditTrail {
  const [showOwnActivity, setShowOwnActivity] = useState(false);
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
  // One filtered list feeds both the timeline and the summary, so the two cannot disagree.
  const visible = filterAuditEntries(entries, showOwnActivity);
  // Recomputed per render on purpose: "2 hours ago" is read from the clock, and a page of
  // this size costs nothing to map.
  const events = toEventViews(visible, labels);

  return {
    status: trailResource.status === "idle" ? "loading" : trailResource.status,
    message: trailResource.status === "error" ? trailResource.message : null,
    events,
    summary: summarizeAuditEntries(visible, events, { showOwnActivity }),
    showOwnActivity,
    setShowOwnActivity,
    hiddenOwnActivity: countOwnRecordAccess(entries),
    truncated: trailResource.status === "ready" && trailResource.data.nextCursor !== null,
    pageSize: MAX_PAGE_SIZE,
    reload: trail.reload,
  };
}
