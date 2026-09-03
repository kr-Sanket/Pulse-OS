// Every backend call the Active Grants page makes.
//
// Same contract as records/api.ts and consent/api.ts: the client is injected, nothing
// throws, every call answers with a discriminated result, and lib/apiResult.ts owns the
// shape. No React here, so the module is unit-testable without a DOM.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, statusFailure, type ApiResult } from "@/lib/apiResult";

export type Grant = components["schemas"]["ConsentGrantListItemResponse"];
/** What revoking answers with — the base grant shape, without the listing's derived state. */
export type RevokedGrant = components["schemas"]["ConsentGrantResponse"];
export type GrantPage = components["schemas"]["ConsentGrantListResponse"];
export type GrantStatus = components["schemas"]["ConsentGrantState"];
export type Grantee = components["schemas"]["StaffDisplayResponse"];

/** Asked for on the listing: the API caps a page at 100 and the page has no pager. */
const MAX_PAGE_SIZE = 100;

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see who has access.",
  403: "This account cannot view consent grants.",
  404: "Your patient profile is not set up yet.",
};

/** Used only where the API sends no problem detail of its own. */
const REVOKE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then withdraw this access.",
  403: "This account is not allowed to withdraw access.",
  404: "This grant is no longer available. Refresh to see the current list.",
  409: "This grant could not be withdrawn in its current state.",
  422: "That withdrawal could not be processed as sent.",
};

/** Every grant ever derived for the patient, newest first — the API's own history view. */
export async function listGrants(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<GrantPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/consent-grants", {
      params: { query: { limit: MAX_PAGE_SIZE } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your active grants.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Withdraw one grant. Idempotent server-side: revoking an already-revoked grant returns it
 * unchanged, which is what makes retrying a partly-failed card safe.
 */
export async function revokeGrant(
  client: PulseOSClient,
  grantId: string,
): Promise<ApiResult<RevokedGrant>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/consent-grants/{grant_id}/revoke", {
      params: { path: { grant_id: grantId } },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        REVOKE_FAILURES,
        "Could not withdraw this access.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
