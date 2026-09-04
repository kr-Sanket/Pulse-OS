// Every backend call the Consent Requests page makes.
//
// Same contract as records/api.ts: the client is injected, nothing throws, every call
// answers with a discriminated result, and the shared plumbing in lib/apiResult.ts owns
// the shape. No React here, so the whole module is unit-testable without a DOM.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type AccessRequest = components["schemas"]["AccessRequestListItemResponse"];
export type AccessRequestPage = components["schemas"]["AccessRequestListResponse"];
export type DecisionOutcome = components["schemas"]["DecisionOutcomeResponse"];
export type RequestStatus = components["schemas"]["ConsentRequestStatus"];
export type Requester = components["schemas"]["StaffDisplayResponse"];

/** Which way a request is being answered. The two endpoints differ only in this word. */
export type DecisionKind = "approve" | "reject";

/** Asked for on the listing: the API caps a page at 100 and the page has no pager. */
const MAX_PAGE_SIZE = 100;

/** Used only where the API sends no problem detail of its own. */
const DECISION_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then answer this request.",
  403: "This account is not allowed to answer consent requests.",
  404: "This request is no longer available. Refresh to see the current list.",
  409: "This request has already been answered, or it has expired.",
  422: "Those record categories are not the ones this request asked for.",
};

const INBOX_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your requests.",
  403: "This account cannot view consent requests.",
  404: "Your patient profile is not set up yet.",
};

/** The patient's consent inbox: requests naming them, newest first. */
export async function listInbox(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<AccessRequestPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/access-requests/inbox", {
      params: { query: { limit: MAX_PAGE_SIZE } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        INBOX_FAILURES,
        "Could not load your consent requests.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Answer a request for a set of categories.
 *
 * `categoryCodes` is passed straight through — the caller sends exactly the codes the
 * request asked for, because the API rejects any category it never named (422) and
 * silently narrowing a patient's answer is not this layer's decision to make.
 *
 * The two endpoints take the same body and return the same outcome, so this is one
 * function; only the path differs, and the typed client needs those as literals.
 */
export async function decideRequest(
  client: PulseOSClient,
  requestId: string,
  categoryCodes: readonly string[],
  kind: DecisionKind,
): Promise<ApiResult<DecisionOutcome>> {
  return attempt(async () => {
    const options = {
      params: { path: { request_id: requestId } },
      body: { categoryCodes: [...categoryCodes] },
    };
    const result =
      kind === "approve"
        ? await client.POST("/api/v1/access-requests/{request_id}/approve", options)
        : await client.POST("/api/v1/access-requests/{request_id}/reject", options);
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        DECISION_FAILURES,
        kind === "approve" ? "Could not approve this request." : "Could not decline this request.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
