import { expect, test, vi } from "vitest";
import type { PulseOSClient } from "@pulseos/api-client";

import {
  fetchUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function ok(data: unknown, status = 200): StubResult {
  return { data, response: { status } };
}

function fail(status: number, error?: unknown): StubResult {
  return { error: error ?? {}, response: { status } };
}

function stubClient(result: StubResult | Error) {
  const getCall = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  const postCall = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return {
    client: { GET: getCall, POST: postCall } as unknown as PulseOSClient,
    getCall,
    postCall,
  };
}

const SIGNAL = new AbortController().signal;

test("fetchUnreadCount issues GET to /api/v1/notifications/unread-count", async () => {
  const { client, getCall } = stubClient(ok({ count: 5 }));

  const result = await fetchUnreadCount(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: { count: 5 } });
  expect(getCall).toHaveBeenCalledWith("/api/v1/notifications/unread-count", {
    signal: SIGNAL,
  });
});

test("fetchUnreadCount translates 401 into session expired message", async () => {
  const { client } = stubClient(fail(401));

  const result = await fetchUnreadCount(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to view notifications.",
  });
});

test("fetchUnreadCount translates 403 into permission message", async () => {
  const { client } = stubClient(fail(403));

  const result = await fetchUnreadCount(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "This account is not permitted to access notifications.",
  });
});

test("listNotifications issues GET with pagination and filter parameters", async () => {
  const page = { items: [], nextCursor: null };
  const { client, getCall } = stubClient(ok(page));

  const result = await listNotifications(
    client,
    { cursor: "cur-1", limit: 20, unreadOnly: true },
    SIGNAL,
  );

  expect(result).toEqual({ status: "ready", data: page });
  expect(getCall).toHaveBeenCalledWith("/api/v1/notifications", {
    params: {
      query: { cursor: "cur-1", limit: 20, unreadOnly: true },
    },
    signal: SIGNAL,
  });
});

test("markNotificationRead issues POST to /api/v1/notifications/{id}/read", async () => {
  const item = { id: "notif-1", title: "Access Requested", isRead: true };
  const { client, postCall } = stubClient(ok(item));

  const result = await markNotificationRead(client, "notif-1");

  expect(result).toEqual({ status: "ready", data: item });
  expect(postCall).toHaveBeenCalledWith("/api/v1/notifications/{id}/read", {
    params: { path: { id: "notif-1" } },
  });
});

test("markNotificationRead maps 404 to not found message", async () => {
  const { client } = stubClient(fail(404));

  const result = await markNotificationRead(client, "notif-missing");

  expect(result).toEqual({
    status: "error",
    message: "Notification not found.",
  });
});

test("markAllNotificationsRead issues POST to /api/v1/notifications/mark-all-read", async () => {
  const outcome = { count: 3 };
  const { client, postCall } = stubClient(ok(outcome));

  const result = await markAllNotificationsRead(client);

  expect(result).toEqual({ status: "ready", data: outcome });
  expect(postCall).toHaveBeenCalledWith("/api/v1/notifications/mark-all-read", {});
});

test("network error is caught and converted to error result", async () => {
  const { client } = stubClient(new Error("Network failed"));

  const result = await fetchUnreadCount(client);

  expect(result.status).toBe("error");
});
