// Access requests, from the clinician's side: raising one and listing the ones raised.
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. No React here, so the whole module is
// unit-testable without a DOM.
//
// Deliberately only two calls. Approving, rejecting and revoking are the patient's, and a
// clinician has no grant listing at all: what a doctor may actually read is answered per
// read by `consent.enforce`, never by a listing (SYSTEM_ARCHITECTURE rule 3).

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

/** A request as the requester's own listing returns it — the shared item projection plus
 * the subject's Health ID, which is what makes the list readable to a clinician. */
export type SentAccessRequest = components["schemas"]["SentAccessRequestResponse"];
export type SentAccessRequestPage = components["schemas"]["SentAccessRequestListResponse"];
/** What POST answers with: no requester projection, because the caller *is* the requester. */
export type CreatedAccessRequest = components["schemas"]["AccessRequestResponse"];
export type ConsentRequestStatus = components["schemas"]["ConsentRequestStatus"];

/** Asked for on the listing: the API caps a page at 100 and the page has no pager yet. */
export const MAX_PAGE_SIZE = 100;

/** The API's own limits, mirrored so a form can stop a doomed request before the round trip.
 * The server remains the authority — these are the same numbers, not a second rule. */
export const MAX_CATEGORIES_PER_REQUEST = 20;
export const MAX_PURPOSE_LENGTH = 255;
export const MAX_HEALTH_ID_LENGTH = 20;

/** Used only where the API sends no problem detail of its own. */
const CREATE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then send this request.",
  403: "Your clinician profile is not active at its hospital, so you cannot request access.",
  404: "No clinician profile is attached to this account yet.",
  422: "Check the Pulse Health ID and the categories you selected, then try again.",
};

const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your requests.",
  403: "This account cannot view access requests.",
  404: "No clinician profile is attached to this account yet.",
  422: "That page of requests could not be loaded.",
};

export interface AccessRequestDraft {
  /** As the patient reads it off their card; the API uppercases and trims. */
  patientHealthId: string;
  /** Category codes, not display names — 1 to MAX_CATEGORIES_PER_REQUEST of them. */
  categoryCodes: readonly string[];
  /** Why access is needed, 1 to MAX_PURPOSE_LENGTH characters. */
  purpose: string;
}

/**
 * Ask a patient for access to a set of record categories.
 *
 * Requires an ACTIVE clinician profile (ADR-015) — a suspended doctor is refused with 403.
 * The resulting request is always PENDING and lapses on its own after the server's TTL;
 * nothing here chooses a duration, and nothing here grants anything.
 */
export async function createAccessRequest(
  client: PulseOSClient,
  draft: AccessRequestDraft,
): Promise<ApiResult<CreatedAccessRequest>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/access-requests", {
      body: {
        patientHealthId: draft.patientHealthId,
        categoryCodes: [...draft.categoryCodes],
        purpose: draft.purpose,
      },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        CREATE_FAILURES,
        "Could not send this access request.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * The clinician's own outgoing requests, newest first.
 *
 * Readable by a non-ACTIVE clinician too: seeing what you asked for is not a clinical
 * capability, so this call is not gated on activation the way creating one is.
 */
export async function listSentRequests(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<SentAccessRequestPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/access-requests/sent", {
      params: { query: { limit: MAX_PAGE_SIZE } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your access requests.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
