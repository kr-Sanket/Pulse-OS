// The Profile page's write call.
//
// Reads live in loadProfile.ts, which is a multi-step bootstrap (GET /me, register on 403,
// refresh, retry) rather than a plain request. This is the ordinary half: one PATCH, the
// injected client, nothing thrown, a discriminated result — the same contract the records,
// consent and audit modules use.
//
// The request carries only the fields the patient actually changed. That is not an
// optimisation: `PATCH /patients/me` treats an omitted key as "leave alone" and an explicit
// `null` as "clear this", so sending an unchanged field would be a write, and sending every
// field would make Cancel-then-Save indistinguishable from a real edit.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type PatientProfile = components["schemas"]["PatientProfileResponse"];
export type ProfileUpdate = components["schemas"]["PatientProfileUpdateRequest"];
export type Gender = PatientProfile["gender"];

/** Per-status wording, used only when the API sends no problem detail of its own. */
const UPDATE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to save your changes.",
  403: "This account is not allowed to edit this profile.",
  404: "Your patient profile is not set up yet.",
  422: "Some of those details could not be saved. Check the fields and try again.",
};

/**
 * Apply a partial profile change and answer with the profile as it now stands.
 *
 * The response is the updated record, so a caller has no reason to re-read afterwards —
 * and re-reading would be worse than pointless, since it could race a second edit.
 */
export async function updateProfile(
  client: PulseOSClient,
  update: ProfileUpdate,
): Promise<ApiResult<PatientProfile>> {
  return attempt(async () => {
    const result = await client.PATCH("/api/v1/patients/me", { body: update });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        UPDATE_FAILURES,
        "Could not save your changes.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
