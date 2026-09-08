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

import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/api";
import { categoryLabels, listCategories } from "@pulseos/ui";
import { useApiResource } from "@pulseos/ui";

import { AUDIT_PAGE_SIZE, listAuditEvents, type AuditEvent } from "./api";
import {
  actorPath,
  countOwnRecordAccess,
  filterAuditEntries,
  groupAuditEvents,
  initialExpansion,
  summarizeAuditEntries,
  toEventViews,
  type AuditEventView,
  type OriginGroup,
  type SummaryStat,
} from "./view";

export interface AuditTrail {
  status: "loading" | "ready" | "error";
  /** Why the trail failed to load, when it did. */
  message: string | null;
  /** The rows to render, flat and newest-first: the whole trail, or everyone else's part
   * of it. Kept alongside the grouped view because the summary counts over it. */
  events: readonly AuditEventView[];
  /** The same events as origin → actor → events. Built from `events`, never from the
   * unfiltered page, so the toggle can never leave a group counting hidden rows. */
  groups: readonly OriginGroup[];
  isOriginExpanded: (key: string) => boolean;
  toggleOrigin: (key: string) => void;
  isActorExpanded: (originKey: string, actorKey: string) => boolean;
  toggleActor: (originKey: string, actorKey: string) => void;
  /** Figures over the visible rows only — the API has no aggregate endpoint. */
  summary: readonly SummaryStat[];
  /** False by default: the page answers "who else touched my records?" first. */
  showOwnActivity: boolean;
  setShowOwnActivity: (show: boolean) => void;
  /** How many of the patient's own reads the default view is holding back. Zero means the
   * timeline is empty because nothing happened, not because something was filtered. */
  hiddenOwnActivity: number;
  /** True when the API has more events than has been loaded. Group counts describe what is
   * loaded, so the page says so rather than implying a lifetime total. */
  truncated: boolean;
  /** A further page is in flight. */
  loadingMore: boolean;
  /** Why the last Load more failed, if it did. */
  moreMessage: string | null;
  loadMore: () => void;
  /** How many events a page holds, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useAudit(): AuditTrail {
  const [showOwnActivity, setShowOwnActivity] = useState(false);
  const loadTrail = useCallback((signal: AbortSignal) => listAuditEvents(api, signal), []);
  const trail = useApiResource(loadTrail);

  // Pages fetched past the first, and the cursor that continues them. A reload — the retry
  // button — refetches the first page, so anything appended under the old cursor stops
  // belonging to this trail and is dropped with it.
  const [appended, setAppended] = useState<readonly AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreMessage, setMoreMessage] = useState<string | null>(null);

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

  // The conditional lives inside the memo: read outside it, the empty-array branch would be
  // a fresh value on every render and the memo would never hold.
  const entries = useMemo(
    () => [...(trailResource.status === "ready" ? trailResource.data.items : []), ...appended],
    [trailResource, appended],
  );

  useEffect(() => {
    if (trailResource.status !== "ready") {
      return;
    }
    setAppended([]);
    setCursor(trailResource.data.nextCursor);
    setMoreMessage(null);
  }, [trailResource]);

  const loadMore = useCallback(() => {
    if (cursor === null || loadingMore) {
      return;
    }
    setLoadingMore(true);
    setMoreMessage(null);
    void listAuditEvents(api, new AbortController().signal, cursor).then((result) => {
      setLoadingMore(false);
      if (result.status === "error") {
        setMoreMessage(result.message);
        return;
      }
      setAppended((previous) => [...previous, ...result.data.items]);
      setCursor(result.data.nextCursor);
    });
  }, [cursor, loadingMore]);

  // One filtered list feeds the timeline, the groups and the summary, so no two can
  // disagree — and grouping sees only what the toggle already allowed through.
  const visible = filterAuditEntries(entries, showOwnActivity);
  // Recomputed per render on purpose: "2 hours ago" is read from the clock, and a page of
  // this size costs nothing to map.
  const events = toEventViews(visible, labels);
  const groups = useMemo(() => groupAuditEvents(visible, labels), [visible, labels]);

  // Default expansion is decided once, from the first grouping that exists, and then left
  // to the reader. Recomputing it as pages arrive would reopen groups they had closed.
  const [expanded, setExpanded] = useState<{
    origins: ReadonlySet<string>;
    actors: ReadonlySet<string>;
  } | null>(null);
  useEffect(() => {
    setExpanded((current) => {
      if (current !== null || groups.length === 0) {
        return current;
      }
      const initial = initialExpansion(groups);
      return { origins: new Set(initial.origins), actors: new Set(initial.actors) };
    });
  }, [groups]);

  const toggle = useCallback((set: ReadonlySet<string>, key: string): Set<string> => {
    const next = new Set(set);
    if (!next.delete(key)) {
      next.add(key);
    }
    return next;
  }, []);

  return {
    status: trailResource.status === "idle" ? "loading" : trailResource.status,
    message: trailResource.status === "error" ? trailResource.message : null,
    events,
    groups,
    isOriginExpanded: (key) => expanded?.origins.has(key) ?? false,
    toggleOrigin: (key) =>
      setExpanded((current) => ({
        origins: toggle(current?.origins ?? new Set(), key),
        actors: current?.actors ?? new Set(),
      })),
    isActorExpanded: (originKey, actorKey) =>
      expanded?.actors.has(actorPath(originKey, actorKey)) ?? false,
    toggleActor: (originKey, actorKey) =>
      setExpanded((current) => ({
        origins: current?.origins ?? new Set(),
        actors: toggle(current?.actors ?? new Set(), actorPath(originKey, actorKey)),
      })),
    summary: summarizeAuditEntries(visible, events, { showOwnActivity }),
    showOwnActivity,
    setShowOwnActivity,
    hiddenOwnActivity: countOwnRecordAccess(entries),
    truncated: cursor !== null,
    loadingMore,
    moreMessage,
    loadMore,
    pageSize: AUDIT_PAGE_SIZE,
    reload: trail.reload,
  };
}
