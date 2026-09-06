// The hospital's own doctor roster, and the two calls that change a doctor's standing
// (ADR-015 step 3).
//
// Same contract as every feature api module in the portals — injected client, nothing
// thrown, the shared result shape from @pulseos/ui. No React here, so the whole module is
// unit-testable without a DOM.
//
// Three calls, and no more: a hospital cannot create, edit or delete a doctor. Doctors
// register themselves, and the row is kept forever once they have — identities referenced by
// records and audit events are never deleted (docs/DATABASE_DESIGN.md principle 5), which is
// why suspending is the strongest action here.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type Doctor = components["schemas"]["DoctorResponse"];
export type DoctorPage = components["schemas"]["DoctorListResponse"];
export type DoctorStatus = components["schemas"]["DoctorStatus"];

/** Asked for on the listing: the API caps a page at 100 and the page has no pager yet. */
export const MAX_PAGE_SIZE = 100;

/** Used only where the API sends no problem detail of its own. */
const LISTING_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to see your doctors.",
  403: "This account cannot manage doctors.",
  404: "No hospital is attached to this account yet.",
  422: "That page of doctors could not be loaded.",
};

/** A 404 here means "unknown doctor **or** a doctor of another hospital" — the API does not
 * distinguish them, by design, so the wording must not claim to know which. */
const ACTION_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again, then try once more.",
  403: "This account cannot manage doctors.",
  404: "That doctor is not on your hospital's roster. Reload the list.",
};

/** The caller's own hospital's doctors, newest first. */
export async function listDoctors(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<DoctorPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/hospitals/me/doctors", {
      params: { query: { limit: MAX_PAGE_SIZE } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LISTING_FAILURES,
        "Could not load your doctors.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Let a doctor act clinically at this hospital. Idempotent.
 *
 * Activation is permission to *ask*, never permission to read: an active doctor can search a
 * Pulse Health ID and request access, and still reaches no record without the patient's
 * consent for that category.
 */
export async function activateDoctor(
  client: PulseOSClient,
  doctorId: string,
): Promise<ApiResult<Doctor>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/hospitals/me/doctors/{doctor_id}/activate", {
      params: { path: { doctor_id: doctorId } },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        ACTION_FAILURES,
        "Could not activate this doctor.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Withdraw a doctor's clinical standing at this hospital. Idempotent.
 *
 * Takes effect on the doctor's very next request: `consent.enforce` refuses a suspended
 * clinician *even where a live grant survives*, so this stops reads immediately. It does not
 * revoke anything — the patients' grants stay exactly as they were, and reactivating restores
 * access without anyone having to consent again.
 */
export async function deactivateDoctor(
  client: PulseOSClient,
  doctorId: string,
): Promise<ApiResult<Doctor>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/hospitals/me/doctors/{doctor_id}/deactivate", {
      params: { path: { doctor_id: doctorId } },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        ACTION_FAILURES,
        "Could not suspend this doctor.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
