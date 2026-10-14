// The Consent Requests page's state: the inbox, the category vocabulary that renders it,
// and one in-flight answer at a time per request.
//
// Two reads go through the shared useApiResource (loading/error/abort/reload for free);
// the writes are held here because they are per-row and must not disturb the rest of the
// page. Answering a request does **not** refetch: the API's own response says what was
// recorded, so the outcome is remembered and the request moves section on the next render.
// That is what keeps the page live without a refresh, and it means a failed answer leaves
// every other row exactly as it was.

import { useCallback, useMemo, useState } from "react";

import { api } from "@/api";
import { useApiResource } from "@pulseos/ui";
import { categoryLabels, listCategories } from "@pulseos/ui";

import { decideRequest, listInbox, type DecisionKind } from "./api";
import {
  groupRequests,
  NO_REQUESTS,
  recordedOutcome,
  type RecordedOutcome,
  type RequestBuckets,
} from "./view";

export interface ConsentInbox {
  /** Mirrors the listing request; the vocabulary loads alongside and never blocks it. */
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  buckets: RequestBuckets;
  /** True when the API has more requests than one page holds. */
  truncated: boolean;
  reload: () => void;
  /** Answer a request with exactly the categories it asked for. */
  decide: (requestId: string, categoryCodes: readonly string[], kind: DecisionKind) => void;
  /** Which answer is in flight for a request, if any. */
  busyOn: (requestId: string) => DecisionKind | null;
  /** Why the last answer to a request failed, if it did. */
  errorOn: (requestId: string) => string | null;
}

export function useConsentInbox(): ConsentInbox {
  const loadInbox = useCallback((signal: AbortSignal) => listInbox(api, signal), []);
  const inbox = useApiResource(loadInbox, { pollIntervalMs: 15_000, refreshOnFocus: true });

  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const [outcomes, setOutcomes] = useState<ReadonlyMap<string, RecordedOutcome>>(new Map());
  const [busy, setBusy] = useState<Readonly<Record<string, DecisionKind>>>({});
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const inboxResource = inbox.resource;
  const vocabularyResource = vocabulary.resource;

  const labels = useMemo(
    () =>
      vocabularyResource.status === "ready"
        ? categoryLabels(vocabularyResource.data)
        : new Map<string, string>(),
    [vocabularyResource],
  );

  const requests = inboxResource.status === "ready" ? inboxResource.data.items : [];
  // Recomputed per render on purpose: relative times ("2 hours ago") are read from the
  // clock, and a page this size costs nothing to regroup.
  const buckets =
    inboxResource.status === "ready" ? groupRequests(requests, labels, outcomes) : NO_REQUESTS;

  async function submit(
    requestId: string,
    categoryCodes: readonly string[],
    kind: DecisionKind,
  ): Promise<void> {
    setBusy((current) => ({ ...current, [requestId]: kind }));
    setErrors((current) => withoutKey(current, requestId));

    const result = await decideRequest(api, requestId, categoryCodes, kind);

    setBusy((current) => withoutKey(current, requestId));
    if (result.status === "error") {
      setErrors((current) => ({ ...current, [requestId]: result.message }));
      return;
    }
    const outcome = recordedOutcome(result.data);
    if (outcome === null) {
      // Some requested category went unanswered, so the request is still open: the server
      // is the authority on what is left, not this page's memory of the click.
      inbox.reload();
      return;
    }
    setOutcomes((current) => new Map(current).set(requestId, outcome));
  }

  return {
    status: inboxResource.status === "idle" ? "loading" : inboxResource.status,
    message: inboxResource.status === "error" ? inboxResource.message : null,
    buckets,
    truncated: inboxResource.status === "ready" && inboxResource.data.nextCursor !== null,
    reload: inbox.reload,
    decide: (requestId, categoryCodes, kind) => void submit(requestId, categoryCodes, kind),
    busyOn: (requestId) => busy[requestId] ?? null,
    errorOn: (requestId) => errors[requestId] ?? null,
  };
}

/** The record without one key — clearing a row's busy flag or its last error. */
function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entry]) => entry !== key));
}
