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
import { listGrants, type Grant } from "@/grants/api";

import { decideRequest, listInbox, type AccessRequest, type DecisionKind } from "./api";
import { groupRequests, NO_REQUESTS, type RecordedOutcome, type RequestBuckets } from "./view";

export interface PerCategoryDecisions {
  approvedCodes: readonly string[];
  rejectedCodes: readonly string[];
}

export interface PartialDecisionState {
  /** Category codes that were successfully approved on the server. */
  approvedCodes: readonly string[];
  /** Category codes whose decline/reject call failed or remaining categories needing a decision. */
  failedCodes: readonly string[];
}

export interface UseConsentInboxOptions {
  /** Optional callback to reload grant state when consent decisions create or modify grants. */
  reloadGrants?: () => void;
  /** Optional pre-loaded or mock grants to use (e.g. for testing or external coordination). */
  grants?: readonly Grant[];
}

export interface ConsentInbox {
  /** Mirrors the listing request; the vocabulary loads alongside and never blocks it. */
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  /** Non-blocking error message from the most recent silent background refresh, if it failed. */
  refreshError: string | null;
  buckets: RequestBuckets;
  /** True when the API has more requests than one page holds. */
  truncated: boolean;
  reload: () => void;
  /** Answer a request with per-category decisions or blanket decisions. */
  decide: (
    requestId: string,
    decisions: PerCategoryDecisions | readonly string[],
    kind?: DecisionKind,
  ) => Promise<void> | void;
  /** Whether an answer is in flight for a request. */
  busyOn: (requestId: string) => boolean;
  /** Why the last answer to a request failed, if it did. */
  errorOn: (requestId: string) => string | null;
  /** Partial decision state if approvals succeeded but rejections failed. */
  partialOn: (requestId: string) => PartialDecisionState | null;
}

/**
 * Identify categories in a pending access request that already have active, authoritative grants on the server.
 *
 * Requirements:
 * 1. The grant must be for the EXACT same doctor: grant.granteeDoctorId === request.requesterDoctorId
 * 2. The grant must be for one of the categories requested: request.categoryCodes.includes(grant.categoryCode)
 * 3. The grant must be currently ACTIVE: grant.status === "ACTIVE" (and not revoked / not expired)
 * 4. The grant must have been granted at or after the request was created:
 *    new Date(grant.grantedAt).getTime() >= new Date(request.createdAt).getTime()
 * 5. Unrelated grants (different doctor, different category, revoked/expired, or granted prior to request creation)
 *    are NEVER treated as proof of approval for this request.
 */
export function findServerApprovedCategoryCodes(
  request: AccessRequest,
  grants: readonly Grant[],
): string[] {
  if (request.status !== "PENDING") {
    return [];
  }

  const requestCreatedAtMs = new Date(request.createdAt).getTime();
  const requestedCodesSet = new Set(request.categoryCodes);

  const approvedCodes = new Set<string>();

  for (const grant of grants) {
    // 1. Must match doctor
    if (grant.granteeDoctorId !== request.requesterDoctorId) {
      continue;
    }

    // 2. Must match one of requested categories
    if (!requestedCodesSet.has(grant.categoryCode)) {
      continue;
    }

    // 3. Must be ACTIVE
    if (grant.status !== "ACTIVE") {
      continue;
    }

    // 4. Must not be revoked
    if (grant.revokedAt !== null && grant.revokedAt !== undefined) {
      continue;
    }

    // 5. Must not be expired
    if (grant.expiresAt && new Date(grant.expiresAt).getTime() <= Date.now()) {
      continue;
    }

    // 6. Must have been granted at or after request creation (with 1s tolerance for timestamp precision)
    const grantedAtMs = new Date(grant.grantedAt).getTime();
    if (
      isNaN(grantedAtMs) ||
      isNaN(requestCreatedAtMs) ||
      grantedAtMs < requestCreatedAtMs - 1000
    ) {
      continue;
    }

    approvedCodes.add(grant.categoryCode);
  }

  // Preserve request's category code ordering
  return request.categoryCodes.filter((code) => approvedCodes.has(code));
}

export function useConsentInbox(options?: UseConsentInboxOptions): ConsentInbox {
  const loadInbox = useCallback((signal: AbortSignal) => listInbox(api, signal), []);
  const inbox = useApiResource(loadInbox, { pollIntervalMs: 15_000, refreshOnFocus: true });

  const loadVocabulary = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const vocabulary = useApiResource(loadVocabulary);

  const loadGrantsList = useCallback((signal: AbortSignal) => listGrants(api, signal), []);
  const grantsResourceHook = useApiResource(options?.grants !== undefined ? null : loadGrantsList, {
    pollIntervalMs: 15_000,
    refreshOnFocus: true,
  });

  const grantsList: readonly Grant[] = useMemo(() => {
    if (options?.grants !== undefined) {
      return options.grants;
    }
    const res = grantsResourceHook.resource;
    return res.status === "ready" ? res.data.items : [];
  }, [options?.grants, grantsResourceHook.resource]);

  const [outcomes, setOutcomes] = useState<ReadonlyMap<string, RecordedOutcome>>(new Map());
  const [busy, setBusy] = useState<Readonly<Record<string, boolean>>>({});
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [partialDecisions, setPartialDecisions] = useState<
    Readonly<Record<string, PartialDecisionState>>
  >({});

  const inboxResource = inbox.resource;
  const vocabularyResource = vocabulary.resource;

  const labels = useMemo(
    () =>
      vocabularyResource.status === "ready"
        ? categoryLabels(vocabularyResource.data)
        : new Map<string, string>(),
    [vocabularyResource],
  );

  const requests = useMemo(
    () => (inboxResource.status === "ready" ? inboxResource.data.items : []),
    [inboxResource],
  );
  // Recomputed per render on purpose: relative times ("2 hours ago") are read from the
  // clock, and a page this size costs nothing to regroup.
  const buckets =
    inboxResource.status === "ready" ? groupRequests(requests, labels, outcomes) : NO_REQUESTS;

  const partialOn = useCallback(
    (requestId: string): PartialDecisionState | null => {
      const req = requests.find((r) => r.id === requestId);
      if (!req || req.status !== "PENDING") {
        return null;
      }

      // 1. Authoritative server state from active grants
      const serverApprovedCodes = findServerApprovedCategoryCodes(req, grantsList);

      // 2. In-session approved codes from this session's successful server responses
      const sessionPartial = partialDecisions[requestId];
      const sessionApproved = sessionPartial ? sessionPartial.approvedCodes : [];

      // Combine server-confirmed and session-confirmed approved codes
      const approvedCodes = req.categoryCodes.filter(
        (code) => serverApprovedCodes.includes(code) || sessionApproved.includes(code),
      );

      // Only treat as partial if at least one category is approved and at least one is still pending
      if (approvedCodes.length === 0 || approvedCodes.length === req.categoryCodes.length) {
        return null;
      }

      const failedOrRemainingCodes = req.categoryCodes.filter(
        (code) => !approvedCodes.includes(code),
      );

      return {
        approvedCodes,
        failedCodes: sessionPartial?.failedCodes?.length
          ? sessionPartial.failedCodes
          : failedOrRemainingCodes,
      };
    },
    [requests, grantsList, partialDecisions],
  );

  async function submit(
    requestId: string,
    decisionsOrCodes: PerCategoryDecisions | readonly string[],
    maybeKind?: DecisionKind,
  ): Promise<void> {
    if (busy[requestId]) {
      return;
    }

    let approvedCodes: readonly string[];
    let rejectedCodes: readonly string[];

    if ("approvedCodes" in decisionsOrCodes) {
      approvedCodes = decisionsOrCodes.approvedCodes;
      rejectedCodes = decisionsOrCodes.rejectedCodes;
    } else {
      const kind = maybeKind ?? "approve";
      approvedCodes = kind === "approve" ? decisionsOrCodes : [];
      rejectedCodes = kind === "reject" ? decisionsOrCodes : [];
    }

    const existingPartial = partialOn(requestId);
    const alreadyApprovedCodes = existingPartial ? existingPartial.approvedCodes : [];
    const pendingApprovedCodes = approvedCodes.filter(
      (code) => !alreadyApprovedCodes.includes(code),
    );

    if (pendingApprovedCodes.length === 0 && rejectedCodes.length === 0) {
      return;
    }

    setBusy((current) => ({ ...current, [requestId]: true }));
    setErrors((current) => withoutKey(current, requestId));

    let newlyApprovedCodes: readonly string[] = [];

    try {
      // 1. Submit approvals if any remain pending
      if (pendingApprovedCodes.length > 0) {
        const result = await decideRequest(api, requestId, pendingApprovedCodes, "approve");
        if (result.status === "error") {
          setErrors((current) => ({ ...current, [requestId]: result.message }));
          inbox.reload();
          grantsResourceHook.reload();
          options?.reloadGrants?.();
          return;
        }
        newlyApprovedCodes = pendingApprovedCodes;
        grantsResourceHook.reload();
        options?.reloadGrants?.();
      }

      const allApprovedCodes = [...alreadyApprovedCodes, ...newlyApprovedCodes];

      // 2. Submit rejections if any
      if (rejectedCodes.length > 0) {
        const result = await decideRequest(api, requestId, rejectedCodes, "reject");
        if (result.status === "error") {
          if (allApprovedCodes.length > 0) {
            const approvedDisplay = allApprovedCodes
              .map((code) => labels.get(code) ?? code)
              .join(", ");
            const partialErrorMessage = `Approved categories (${approvedDisplay}) may already have access granted, while the remaining categories still need a decision: ${result.message}`;
            setErrors((current) => ({ ...current, [requestId]: partialErrorMessage }));
            setPartialDecisions((current) => ({
              ...current,
              [requestId]: {
                approvedCodes: allApprovedCodes,
                failedCodes: rejectedCodes,
              },
            }));
          } else {
            setErrors((current) => ({ ...current, [requestId]: result.message }));
          }
          inbox.reload();
          grantsResourceHook.reload();
          options?.reloadGrants?.();
          return;
        }
      }

      // 3. Whole decision succeeded! Clear partial state
      setPartialDecisions((current) => withoutKey(current, requestId));

      // Mark outcome (any approval means the request yielded granted access)
      const recorded: RecordedOutcome = allApprovedCodes.length > 0 ? "approved" : "rejected";
      setOutcomes((current) => new Map(current).set(requestId, recorded));

      // 4. Reload inbox and grant state
      inbox.reload();
      grantsResourceHook.reload();
      options?.reloadGrants?.();
    } finally {
      setBusy((current) => withoutKey(current, requestId));
    }
  }

  return {
    status: inboxResource.status === "idle" ? "loading" : inboxResource.status,
    message: inboxResource.status === "error" ? inboxResource.message : null,
    refreshError: inbox.refreshError ?? grantsResourceHook.refreshError,
    buckets,
    truncated: inboxResource.status === "ready" && inboxResource.data.nextCursor !== null,
    reload: () => {
      inbox.reload();
      grantsResourceHook.reload();
      options?.reloadGrants?.();
    },
    decide: (requestId, decisions, kind) => void submit(requestId, decisions, kind),
    busyOn: (requestId) => Boolean(busy[requestId]),
    errorOn: (requestId) => errors[requestId] ?? null,
    partialOn,
  };
}

/** The record without one key — clearing a row's busy flag or its last error. */
function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entry]) => entry !== key));
}
