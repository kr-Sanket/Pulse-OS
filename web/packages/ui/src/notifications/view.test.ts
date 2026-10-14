import { expect, test } from "vitest";

import type { NotificationItem } from "./api";
import { badgeCountLabel, eventTypeMeta, toNotificationViewItem } from "./view";

test("badgeCountLabel returns null when count is zero or negative", () => {
  expect(badgeCountLabel(0)).toBeNull();
  expect(badgeCountLabel(-1)).toBeNull();
});

test("badgeCountLabel returns numeric string up to 99", () => {
  expect(badgeCountLabel(1)).toBe("1");
  expect(badgeCountLabel(42)).toBe("42");
  expect(badgeCountLabel(99)).toBe("99");
});

test("badgeCountLabel returns '99+' when exceeding 99", () => {
  expect(badgeCountLabel(100)).toBe("99+");
  expect(badgeCountLabel(500)).toBe("99+");
});

test("eventTypeMeta maps all four consent lifecycle event types", () => {
  const req = eventTypeMeta("ACCESS_REQUESTED");
  expect(req.label).toBe("Access Requested");
  expect(req.badgeVariant).toBe("warning");

  const app = eventTypeMeta("CONSENT_APPROVED");
  expect(app.label).toBe("Access Approved");
  expect(app.badgeVariant).toBe("success");

  const rej = eventTypeMeta("CONSENT_REJECTED");
  expect(rej.label).toBe("Access Declined");
  expect(rej.badgeVariant).toBe("destructive");

  const rev = eventTypeMeta("CONSENT_REVOKED");
  expect(rev.label).toBe("Access Revoked");
  expect(rev.badgeVariant).toBe("neutral");
});

test("toNotificationViewItem formats item with relative time and metadata", () => {
  const item: NotificationItem = {
    id: "notif-uuid-1",
    eventType: "CONSENT_APPROVED",
    title: "Access Approved",
    message: "Patient granted access to Lab Reports.",
    isRead: false,
    createdAt: "2026-10-13T10:00:00Z",
    referenceRequestId: "req-1",
  };

  const now = new Date("2026-10-13T12:00:00Z").getTime();
  const view = toNotificationViewItem(item, now);

  expect(view.id).toBe("notif-uuid-1");
  expect(view.isRead).toBe(false);
  expect(view.meta.label).toBe("Access Approved");
  expect(view.timeAgo).toBe("2 hours ago");
  expect(view.referenceRequestId).toBe("req-1");
});
