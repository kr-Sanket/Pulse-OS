// The Active Grants page's state: the listing, the category vocabulary that renders it, and
// one withdrawal at a time per card.
//
// Two reads go through the shared useApiResource (loading/error/abort/reload for free); the
// writes are held here because they are per-card. Withdrawing does not refetch: the rows a
// card stands for are remembered as revoked, grouping re-files the card on the next render,
// and every other card is left exactly as it was.

import { useCallback, useMemo, useState } from "react";

import { api } from "@/api";
import { categoryLabels, listCategories } from "@/lib/recordCategories";
import { useApiResource } from "@pulseos/ui";

import { listGrants, revokeGrant } from "./api";
import {
  applyRevocations,
  bucketGrants,
  groupGrants,
  NO_GRANTS,
  type GrantBuckets,
  type GrantGroupView,
} from "./view";

export interface GrantsResource {
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  buckets: GrantBuckets;
  /** True when the API has more grants than one page holds. */
  truncated: boolean;
  reload: () => void;
  /** Withdraw every grant row the card stands for. */
  revoke: (group: GrantGroupView) => void;
  /** Whether a withdrawal is in flight for a card. */
  busyOn: (groupId: string) => boolean;
  /** Why the last withdrawal from a card failed, if it did. */
  errorOn: (groupId: string) => string | null;
}

export function useGrants(): GrantsResource {
  const loadGrants = useCallback((signal: AbortSignal) => listGrants(api, signal), []);
  const grants = useApiResource(loadGrants);

  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const [revokedIds, setRevokedIds] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const grantsResource = grants.resource;
  const vocabularyResource = vocabulary.resource;

  const labels = useMemo(
    () =>
      vocabularyResource.status === "ready"
        ? categoryLabels(vocabularyResource.data)
        : new Map<string, string>(),
    [vocabularyResource],
  );

  // Recomputed per render on purpose: "6 days remaining" is read from the clock, and a page
  // of this size costs nothing to regroup.
  const buckets =
    grantsResource.status === "ready"
      ? bucketGrants(
          groupGrants(
            applyRevocations(grantsResource.data.items, revokedIds, new Date().toISOString()),
            labels,
          ),
        )
      : NO_GRANTS;

  async function withdraw(group: GrantGroupView): Promise<void> {
    setBusy((current) => new Set(current).add(group.id));
    setErrors((current) => withoutKey(current, group.id));

    // One call per category the card stands for. They are independent rows, so they go out
    // together; the first failure in list order is the one reported.
    const results = await Promise.all(group.grantIds.map((grantId) => revokeGrant(api, grantId)));

    setBusy((current) => withoutSetEntry(current, group.id));
    const failed = results.find((result) => result.status === "error");
    if (failed !== undefined && failed.status === "error") {
      // The card is left exactly as it was. Revoking is idempotent, so pressing it again
      // retries only what did not take.
      setErrors((current) => ({ ...current, [group.id]: failed.message }));
      return;
    }
    setRevokedIds((current) => {
      const next = new Set(current);
      for (const grantId of group.grantIds) {
        next.add(grantId);
      }
      return next;
    });
  }

  return {
    status: grantsResource.status === "idle" ? "loading" : grantsResource.status,
    message: grantsResource.status === "error" ? grantsResource.message : null,
    buckets,
    truncated: grantsResource.status === "ready" && grantsResource.data.nextCursor !== null,
    reload: grants.reload,
    revoke: (group) => void withdraw(group),
    busyOn: (groupId) => busy.has(groupId),
    errorOn: (groupId) => errors[groupId] ?? null,
  };
}

/** The record without one key — clearing a card's last error. */
function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entry]) => entry !== key));
}

function withoutSetEntry(values: ReadonlySet<string>, value: string): Set<string> {
  const next = new Set(values);
  next.delete(value);
  return next;
}
