// Presentation models, status badges, and formatting for Notifications (ADR-031).
//
// Pure presentation logic: transforms backend schema objects into view-ready
// representations with relative timestamps, human-friendly event labels, and
// accessible badge counts. No React dependencies — fully unit-testable.

import type { components } from "@pulseos/api-client";

import { formatRelativeTime } from "../lib/dates";

export type NotificationItem = components["schemas"]["NotificationResponse"];
export type NotificationEventType = components["schemas"]["NotificationEventType"];

export interface NotificationEventMeta {
  badgeVariant: "default" | "success" | "warning" | "destructive" | "neutral" | "info";
  label: string;
  dotColor: string;
}

/**
 * Maps an event type to human-readable label, badge variant, and dot color.
 */
export function eventTypeMeta(eventType: NotificationEventType): NotificationEventMeta {
  switch (eventType) {
    case "ACCESS_REQUESTED":
      return {
        badgeVariant: "warning",
        label: "Access Requested",
        dotColor: "bg-warning",
      };
    case "CONSENT_APPROVED":
      return {
        badgeVariant: "success",
        label: "Access Approved",
        dotColor: "bg-success",
      };
    case "CONSENT_REJECTED":
      return {
        badgeVariant: "destructive",
        label: "Access Declined",
        dotColor: "bg-destructive",
      };
    case "CONSENT_REVOKED":
      return {
        badgeVariant: "neutral",
        label: "Access Revoked",
        dotColor: "bg-muted-foreground",
      };
    default:
      return {
        badgeVariant: "neutral",
        label: "Update",
        dotColor: "bg-primary",
      };
  }
}

/**
 * Determines the text for the notification count pill.
 * Returns null if count <= 0 (pill should be hidden).
 * Returns "99+" for counts exceeding 99.
 */
export function badgeCountLabel(count: number): string | null {
  if (count <= 0) {
    return null;
  }
  if (count > 99) {
    return "99+";
  }
  return String(count);
}

export interface NotificationViewItem {
  id: string;
  eventType: NotificationEventType;
  title: string;
  message: string;
  isRead: boolean;
  timeAgo: string;
  createdAt: string;
  referenceRequestId: string | null;
  meta: NotificationEventMeta;
}

/**
 * Transforms an API response notification item into a formatted view item.
 */
export function toNotificationViewItem(
  item: NotificationItem,
  nowMs: number = Date.now(),
): NotificationViewItem {
  return {
    id: item.id,
    eventType: item.eventType,
    title: item.title,
    message: item.message,
    isRead: item.isRead,
    timeAgo: formatRelativeTime(item.createdAt, nowMs),
    createdAt: item.createdAt,
    referenceRequestId: item.referenceRequestId ?? null,
    meta: eventTypeMeta(item.eventType),
  };
}

export const NO_NOTIFICATIONS_TITLE = "No notifications";
export const NO_NOTIFICATIONS_DESC =
  "You're all caught up! Updates regarding consent and access requests will appear here.";
export const NOTIFICATIONS_TITLE = "Notifications";
export const MARK_ALL_READ_LABEL = "Mark all as read";
