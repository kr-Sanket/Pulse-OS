// API client wrappers for Notifications module (ADR-031).
//
// Follows the same contract as all PulseOS API modules: the client is injected,
// nothing throws, every call returns an ApiResult<T> discriminated union, and
// RFC 7807 problem details take precedence over fallback status messages.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, statusFailure, type ApiResult } from "../lib/apiResult";

export type NotificationItem = components["schemas"]["NotificationResponse"];
export type NotificationListPage = components["schemas"]["NotificationListResponse"];
export type UnreadCount = components["schemas"]["UnreadCountResponse"];
export type MarkAllReadResult = components["schemas"]["MarkAllReadResponse"];
export type NotificationEventType = components["schemas"]["NotificationEventType"];

const NOTIFICATION_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to view notifications.",
  403: "This account is not permitted to access notifications.",
  404: "Notification not found.",
};

/**
 * Fetch the current unread count for the authenticated user.
 */
export async function fetchUnreadCount(
  client: PulseOSClient,
  signal?: AbortSignal,
): Promise<ApiResult<UnreadCount>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/notifications/unread-count", { signal });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        NOTIFICATION_FAILURES,
        "Could not load unread notification count.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

export interface ListNotificationsOptions {
  cursor?: string | null;
  limit?: number;
  unreadOnly?: boolean;
}

/**
 * List notifications for the authenticated user, newest first.
 */
export async function listNotifications(
  client: PulseOSClient,
  options?: ListNotificationsOptions,
  signal?: AbortSignal,
): Promise<ApiResult<NotificationListPage>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/notifications", {
      params: {
        query: {
          cursor: options?.cursor ?? undefined,
          limit: options?.limit ?? undefined,
          unreadOnly: options?.unreadOnly ?? undefined,
        },
      },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        NOTIFICATION_FAILURES,
        "Could not load notifications.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Mark a single notification as read (idempotent).
 */
export async function markNotificationRead(
  client: PulseOSClient,
  id: string,
  signal?: AbortSignal,
): Promise<ApiResult<NotificationItem>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/notifications/{id}/read", {
      params: { path: { id } },
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        NOTIFICATION_FAILURES,
        "Could not mark notification as read.",
      );
    }
    return { status: "ready", data: result.data };
  });
}

/**
 * Mark all unread notifications for the caller as read.
 */
export async function markAllNotificationsRead(
  client: PulseOSClient,
  signal?: AbortSignal,
): Promise<ApiResult<MarkAllReadResult>> {
  return attempt(async () => {
    const result = await client.POST("/api/v1/notifications/mark-all-read", {
      signal,
    });
    if (result.data === undefined) {
      return statusFailure(
        result.error,
        result.response.status,
        NOTIFICATION_FAILURES,
        "Could not mark all notifications as read.",
      );
    }
    return { status: "ready", data: result.data };
  });
}
