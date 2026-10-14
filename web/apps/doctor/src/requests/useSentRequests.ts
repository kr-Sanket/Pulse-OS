// The My Requests page's state: the clinician's own outgoing requests, grouped.
//
// Two reads through the shared useApiResource — the listing, and the category vocabulary
// that renders its codes as words. Read-only by design: this page answers "what did I ask
// for, and where did it get to", and nothing on it mutates anything.

import { useCallback, useMemo } from "react";

import { categoryLabels, listCategories, useApiResource } from "@pulseos/ui";

import { api } from "@/api";

import { listSentRequests, MAX_PAGE_SIZE } from "./api";
import { groupSentRequests, NO_REQUESTS, toSentRequestViews, type RequestBuckets } from "./view";

export interface SentRequestsResource {
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  buckets: RequestBuckets;
  /** How many requests the page holds in total — drives the empty state. */
  total: number;
  /** True when the API has more requests than one page holds. */
  truncated: boolean;
  /** How many a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useSentRequests(): SentRequestsResource {
  const loadRequests = useCallback((signal: AbortSignal) => listSentRequests(api, signal), []);
  const requests = useApiResource(loadRequests, { pollIntervalMs: 15_000, refreshOnFocus: true });

  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const requestsResource = requests.resource;
  const vocabularyResource = vocabulary.resource;

  const labels = useMemo(
    () =>
      vocabularyResource.status === "ready"
        ? categoryLabels(vocabularyResource.data)
        : new Map<string, string>(),
    [vocabularyResource],
  );

  const items = requestsResource.status === "ready" ? requestsResource.data.items : [];
  // Recomputed per render on purpose: "requested 2 hours ago" is read from the clock, and a
  // page of this size costs nothing to regroup.
  const buckets =
    requestsResource.status === "ready"
      ? groupSentRequests(toSentRequestViews(items, labels))
      : NO_REQUESTS;

  return {
    status: requestsResource.status === "idle" ? "loading" : requestsResource.status,
    message: requestsResource.status === "error" ? requestsResource.message : null,
    buckets,
    total: items.length,
    truncated: requestsResource.status === "ready" && requestsResource.data.nextCursor !== null,
    pageSize: MAX_PAGE_SIZE,
    reload: requests.reload,
  };
}
