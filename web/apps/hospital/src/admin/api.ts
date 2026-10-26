// System Admin API calls for hospital verification.
//
// Follows the same contract as all feature api modules in the portals:
// the client is injected, nothing throws, and lib/apiResult owns the shape.
// Backend authorization: RequireSystemAdmin on POST /api/v1/hospitals/{hid}/verify.

import type { components, PulseOSClient } from "@pulseos/api-client";
import { attempt, statusFailure, type ApiResult } from "@pulseos/ui";

export type Hospital = components["schemas"]["HospitalResponse"];
export type HospitalList = components["schemas"]["HospitalListResponse"];
export type HospitalVerificationStatus = components["schemas"]["HospitalVerificationStatus"];
export type AuthenticatedUser = components["schemas"]["AuthenticatedUserResponse"];
export type HospitalAuditLog = components["schemas"]["HospitalAuditLogResponse"];
export type HospitalAuditLogList = components["schemas"]["HospitalAuditLogListResponse"];
export type HospitalLifecycleAction = components["schemas"]["HospitalLifecycleAction"];

const VERIFY_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again as a System Administrator.",
  403: "Access denied. Only PulseOS System Administrators are authorized to verify hospitals.",
  404: "Hospital not found. Check the Hospital ID (HID) and try again.",
  409: "This status transition is not permitted.",
  422: "Invalid Hospital ID format.",
};

const LIFECYCLE_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again as a System Administrator.",
  403: "Access denied. Only PulseOS System Administrators are authorized to manage hospital lifecycle.",
  404: "Hospital not found. Check the Hospital ID (HID) and try again.",
  409: "This status transition is not permitted.",
  422: "Invalid request data. Please check the reason length and format.",
};

const LIST_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again as a System Administrator.",
  403: "Access denied. Only PulseOS System Administrators are authorized to view the hospital directory.",
};

const AUTH_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again.",
  403: "Your account is not provisioned on PulseOS.",
};

/**
 * Mark a hospital VERIFIED.
 * Endpoint: POST /api/v1/hospitals/{hid}/verify (ADR-015 step 2).
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function verifyHospital(
  client: PulseOSClient,
  hid: string,
): Promise<ApiResult<Hospital>> {
  return attempt<Hospital>(async () => {
    const normalizedHid = hid.trim().toUpperCase();
    const result = await client.POST("/api/v1/hospitals/{hid}/verify", {
      params: { path: { hid: normalizedHid } },
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        VERIFY_FAILURES,
        "Could not verify this hospital.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Introspect the current authenticated user's role on PulseOS.
 * Endpoint: GET /api/v1/auth/me.
 */
export async function fetchCurrentUser(
  client: PulseOSClient,
  signal?: AbortSignal,
): Promise<ApiResult<AuthenticatedUser>> {
  return attempt<AuthenticatedUser>(async () => {
    const result = await client.GET("/api/v1/auth/me", { signal });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        AUTH_FAILURES,
        "Could not read your account role.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

export interface ListHospitalsOptions {
  status?: HospitalVerificationStatus;
  signal?: AbortSignal;
}

/**
 * List registered hospitals for platform administration.
 * Endpoint: GET /api/v1/hospitals.
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function listHospitals(
  client: PulseOSClient,
  options?: ListHospitalsOptions,
): Promise<ApiResult<HospitalList>> {
  return attempt<HospitalList>(async () => {
    const result = await client.GET("/api/v1/hospitals", {
      params: {
        query: options?.status ? { status: options.status } : undefined,
      },
      signal: options?.signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LIST_FAILURES,
        "Could not load hospitals from the server.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Reject a pending hospital registration with an optional reason.
 * Endpoint: POST /api/v1/hospitals/{hid}/reject (ADR-034).
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function rejectHospital(
  client: PulseOSClient,
  hid: string,
  reason?: string,
): Promise<ApiResult<Hospital>> {
  return attempt<Hospital>(async () => {
    const normalizedHid = hid.trim().toUpperCase();
    const result = await client.POST("/api/v1/hospitals/{hid}/reject", {
      params: { path: { hid: normalizedHid } },
      body: reason ? { reason } : {},
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LIFECYCLE_FAILURES,
        "Could not reject this hospital.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Suspend a verified hospital with an optional reason.
 * Endpoint: POST /api/v1/hospitals/{hid}/suspend (ADR-034).
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function suspendHospital(
  client: PulseOSClient,
  hid: string,
  reason?: string,
): Promise<ApiResult<Hospital>> {
  return attempt<Hospital>(async () => {
    const normalizedHid = hid.trim().toUpperCase();
    const result = await client.POST("/api/v1/hospitals/{hid}/suspend", {
      params: { path: { hid: normalizedHid } },
      body: reason ? { reason } : {},
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LIFECYCLE_FAILURES,
        "Could not suspend this hospital.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Reinstate a suspended hospital with an optional reason.
 * Endpoint: POST /api/v1/hospitals/{hid}/reinstate (ADR-034).
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function reinstateHospital(
  client: PulseOSClient,
  hid: string,
  reason?: string,
): Promise<ApiResult<Hospital>> {
  return attempt<Hospital>(async () => {
    const normalizedHid = hid.trim().toUpperCase();
    const result = await client.POST("/api/v1/hospitals/{hid}/reinstate", {
      params: { path: { hid: normalizedHid } },
      body: reason ? { reason } : {},
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LIFECYCLE_FAILURES,
        "Could not reinstate this hospital.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Fetch a hospital's administrative lifecycle audit history.
 * Endpoint: GET /api/v1/hospitals/{hid}/audit-logs (ADR-034).
 * Authorization: SYSTEM_ADMIN role only.
 */
export async function fetchHospitalAuditLogs(
  client: PulseOSClient,
  hid: string,
  signal?: AbortSignal,
): Promise<ApiResult<HospitalAuditLogList>> {
  return attempt<HospitalAuditLogList>(async () => {
    const normalizedHid = hid.trim().toUpperCase();
    const result = await client.GET("/api/v1/hospitals/{hid}/audit-logs", {
      params: { path: { hid: normalizedHid } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        LIFECYCLE_FAILURES,
        "Could not load lifecycle audit history.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
