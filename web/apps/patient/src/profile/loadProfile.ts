// The profile bootstrap flow (M0.3 gate): GET /patients/me, transparently registering
// on first login. Pure logic with injected client/refresh so it is unit-testable.
//
// Flow: /me → 403 means "authentic Firebase subject without PulseOS claims" (see
// auth module) → POST /patients/register → force-refresh the ID token so the new
// claims are in it → retry /me. Any other failure surfaces as a message.

import { problemDetail, type PatientProfile, type PulseOSClient } from "@pulseos/api-client";

export interface RegistrationIdentity {
  displayName: string | null;
  email: string | null;
}

export type ProfileResult =
  { status: "ready"; profile: PatientProfile } | { status: "error"; message: string };

/** Registration is transparent, so the full name comes from the identity provider:
 * display name, else the email local part, else a placeholder (editable post-MVP). */
export function registrationFullName(identity: RegistrationIdentity): string {
  const displayName = identity.displayName?.trim();
  if (displayName) {
    return displayName.slice(0, 120);
  }
  const emailLocalPart = identity.email?.split("@")[0]?.trim();
  if (emailLocalPart) {
    return emailLocalPart.slice(0, 120);
  }
  return "PulseOS Patient";
}

function failure(error: unknown, fallback: string): ProfileResult {
  return { status: "error", message: problemDetail(error) ?? fallback };
}

export async function loadOrRegisterProfile(
  client: PulseOSClient,
  identity: RegistrationIdentity,
  refreshToken: () => Promise<void>,
): Promise<ProfileResult> {
  const first = await client.GET("/api/v1/patients/me");
  if (first.data !== undefined) {
    return { status: "ready", profile: first.data };
  }
  if (first.response.status !== 403) {
    return failure(first.error, "Could not load your profile.");
  }

  const registration = await client.POST("/api/v1/patients/register", {
    body: { fullName: registrationFullName(identity) },
  });
  if (registration.data === undefined) {
    // e.g. 409: this account already has a different (non-patient) role.
    return failure(registration.error, "Registration failed.");
  }

  await refreshToken(); // the provisioned claims only exist in a fresh ID token

  const retry = await client.GET("/api/v1/patients/me");
  if (retry.data !== undefined) {
    return { status: "ready", profile: retry.data };
  }
  return failure(retry.error, "Could not load your profile after registration.");
}
