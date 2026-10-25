// The result shape every feature's API module answers with, and the two helpers that build
// it. Extracted from records/api.ts when the consent slice needed the same plumbing —
// "one call, one discriminated result, nothing thrown" is a portal-wide convention now,
// not a records detail.
//
// Nothing here imports React or a specific endpoint: features own their endpoints and
// their wording, this owns the shape.

import { problemDetail } from "@pulseos/api-client";

export type ApiResult<T> = { status: "ready"; data: T } | { status: "error"; message: string };

/** Shown when the request never reached the API at all. */
export const NETWORK_FAILURE = "Could not reach PulseOS. Check your connection and try again.";

/** The API's own RFC 7807 detail wherever it sent one, and the caller's wording otherwise. */
export function failure(error: unknown, fallback: string): ApiResult<never> {
  return { status: "error", message: problemDetail(error) ?? fallback };
}

/** Turns a rejected fetch (offline, DNS, abort) into the same result shape as an HTTP error. */
export async function attempt<T>(call: () => Promise<ApiResult<T>>): Promise<ApiResult<T>> {
  try {
    return await call();
  } catch {
    return { status: "error", message: NETWORK_FAILURE };
  }
}

/** Per-status wording for a call, used only where the API sends no problem detail —
 * FastAPI's 422 body is a field list rather than a sentence, so a fallback is not optional. */
export function statusFailure(
  error: unknown,
  status: number,
  wording: Readonly<Record<number, string>>,
  fallback: string,
): ApiResult<never> {
  return failure(error, wording[status] ?? fallback);
}

/** The API's detail for a suspended account (backend auth/dependencies.py `to_http_error`).
 * Matched exactly: the problem envelope carries no machine-readable code yet, so this
 * string is the contract, and test_auth_http pins it server-side. */
export const ACCOUNT_SUSPENDED_DETAIL = "Account is suspended.";

/** What a suspended user is told, in every portal. */
export const ACCOUNT_SUSPENDED_MESSAGE =
  "This PulseOS account is suspended. Contact your administrator to restore access.";

/**
 * True for the 403 a suspended account gets on every authenticated request.
 *
 * Profile bootstraps treat other 403s as "not registered yet" and send the user to
 * onboarding (or, for patients, register them). A suspended account must not take that
 * path: registration would be refused, and onboarding would misdescribe the account.
 */
export function isAccountSuspended(status: number, error: unknown): boolean {
  return status === 403 && problemDetail(error) === ACCOUNT_SUSPENDED_DETAIL;
}
