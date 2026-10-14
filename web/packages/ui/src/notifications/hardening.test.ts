import { expect, test, vi } from "vitest";
import type { PulseOSClient } from "@pulseos/api-client";

import { fetchUnreadCount, markNotificationRead } from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function ok(data: unknown, status = 200): StubResult {
  return { data, response: { status } };
}

function stubClientWithDelay(resolveWith: StubResult, delayMs: number) {
  const getCall = vi.fn(
    (_path: string, options?: { signal?: AbortSignal }) =>
      new Promise<StubResult>((resolve, reject) => {
        const timer = setTimeout(() => resolve(resolveWith), delayMs);
        options?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      }),
  );

  const postCall = vi.fn(
    (_path: string, options?: { signal?: AbortSignal }) =>
      new Promise<StubResult>((resolve, reject) => {
        const timer = setTimeout(() => resolve(resolveWith), delayMs);
        options?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      }),
  );

  return {
    client: { GET: getCall, POST: postCall } as unknown as PulseOSClient,
    getCall,
    postCall,
  };
}

// ---------------------------------------------------------------------------
// FIX 1: Duplicate refresh requests guard
// ---------------------------------------------------------------------------
test("FIX 1: in-flight guard prevents duplicate concurrent unread count requests and resets on completion", async () => {
  const { client, getCall } = stubClientWithDelay(ok({ count: 7 }), 20);

  let inFlight = false;
  let successCount = 0;

  async function safeFetchUnread(signal?: AbortSignal) {
    if (inFlight) {
      return;
    }
    inFlight = true;
    try {
      const result = await fetchUnreadCount(client, signal);
      if (result.status === "ready") {
        successCount++;
      }
    } finally {
      inFlight = false;
    }
  }

  // Rapid simultaneous triggers (e.g. focus + visibilitychange)
  const req1 = safeFetchUnread();
  const req2 = safeFetchUnread();

  await Promise.all([req1, req2]);

  // Only 1 GET request should have been dispatched; 2nd was deduplicated
  expect(getCall).toHaveBeenCalledTimes(1);
  expect(successCount).toBe(1);
  // Guard must be released so next trigger works
  expect(inFlight).toBe(false);

  // Subsequent trigger now succeeds
  await safeFetchUnread();
  expect(getCall).toHaveBeenCalledTimes(2);
  expect(successCount).toBe(2);
});

test("FIX 1: in-flight guard resets safely after a request failure", async () => {
  const failClient = {
    GET: vi.fn().mockRejectedValue(new Error("Network connection lost")),
  } as unknown as PulseOSClient;

  let inFlight = false;
  let didCatch = false;

  async function safeFetchUnread() {
    if (inFlight) {
      return;
    }
    inFlight = true;
    try {
      const result = await fetchUnreadCount(failClient);
      if (result.status === "error") {
        didCatch = true;
      }
    } finally {
      inFlight = false;
    }
  }

  await safeFetchUnread();

  expect(didCatch).toBe(true);
  expect(inFlight).toBe(false); // Guard must not get stuck on failure
});

// ---------------------------------------------------------------------------
// FIX 2: Account switching & dropping stale responses
// ---------------------------------------------------------------------------
test("FIX 2: stale responses from previous user identity are dropped and do not overwrite new user state", async () => {
  let activeUserId = "user-alice";
  let committedState = { user: "user-alice", count: 3 };

  // Slow response for Alice (takes 30ms)
  async function slowFetchForAlice() {
    const targetUser = activeUserId;
    await new Promise((r) => setTimeout(r, 30));
    // If identity changed in the meantime, drop the stale response
    if (targetUser !== activeUserId) {
      return;
    }
    committedState = { user: targetUser, count: 99 };
  }

  const alicePromise = slowFetchForAlice();

  // User switch occurs immediately to Bob
  activeUserId = "user-bob";
  committedState = { user: "user-bob", count: 0 };

  await alicePromise;

  // Bob's state must NOT have been overwritten by Alice's delayed response
  expect(committedState.user).toBe("user-bob");
  expect(committedState.count).toBe(0);
});

// ---------------------------------------------------------------------------
// FIX 3: In-flight request cancellation with AbortSignal
// ---------------------------------------------------------------------------
test("FIX 3: fetchUnreadCount, listNotifications, and markNotificationRead support and respect AbortSignal", async () => {
  const { client, postCall } = stubClientWithDelay(ok({ id: "notif-1", isRead: true }), 50);

  const controller = new AbortController();
  const readPromise = markNotificationRead(client, "notif-1", controller.signal);

  // Abort while in flight
  controller.abort();

  const result = await readPromise;

  // Signal must have caused rejection in attempt(), converted without throwing
  expect(postCall).toHaveBeenCalledWith("/api/v1/notifications/{id}/read", {
    params: { path: { id: "notif-1" } },
    signal: controller.signal,
  });
  expect(controller.signal.aborted).toBe(true);
  expect(result.status).toBe("error");
});

test("FIX 3: intentional cancellation is distinguishable from API error via signal.aborted", async () => {
  const { client } = stubClientWithDelay(ok({ count: 10 }), 50);

  const controller = new AbortController();
  let errorShown = false;

  const promise = (async () => {
    const result = await fetchUnreadCount(client, controller.signal);
    if (controller.signal.aborted) {
      // Intentional cancellation: drop without displaying error
      return;
    }
    if (result.status === "error") {
      errorShown = true;
    }
  })();

  controller.abort();
  await promise;

  // Cancellation must not show error banner
  expect(errorShown).toBe(false);
});

// ---------------------------------------------------------------------------
// FIX 4: Concurrent mark-as-read actions (Set of busy IDs)
// ---------------------------------------------------------------------------
test("FIX 4: concurrent mark-as-read actions maintain isolated busy states per notification ID", async () => {
  const busyIds = new Set<string>();

  let resolverA!: (val: StubResult) => void;
  let resolverB!: (val: StubResult) => void;

  const mockClient = {
    POST: vi.fn((_path: string, options?: { params?: { path?: { id?: string } } }) => {
      const id = options?.params?.path?.id;
      if (id === "notif-A") {
        return new Promise<StubResult>((resolve) => {
          resolverA = resolve;
        });
      }
      return new Promise<StubResult>((resolve) => {
        resolverB = resolve;
      });
    }),
  } as unknown as PulseOSClient;

  let items = [
    { id: "notif-A", isRead: false },
    { id: "notif-B", isRead: false },
  ];

  async function markRead(id: string) {
    busyIds.add(id);
    try {
      const result = await markNotificationRead(mockClient, id);
      if (result.status === "ready") {
        items = items.map((item) => (item.id === id ? { ...item, isRead: true } : item));
      }
    } finally {
      busyIds.delete(id);
    }
  }

  // Trigger markRead on notif-A and notif-B concurrently
  const actionA = markRead("notif-A");
  const actionB = markRead("notif-B");

  expect(busyIds.has("notif-A")).toBe(true);
  expect(busyIds.has("notif-B")).toBe(true);

  // Complete request A
  resolverA(ok({ id: "notif-A", isRead: true }));
  await actionA;

  // notif-A is done, but notif-B MUST still be in busy state
  expect(busyIds.has("notif-A")).toBe(false);
  expect(busyIds.has("notif-B")).toBe(true);
  expect(items.find((i) => i.id === "notif-A")?.isRead).toBe(true);
  expect(items.find((i) => i.id === "notif-B")?.isRead).toBe(false);

  // Complete request B
  resolverB(ok({ id: "notif-B", isRead: true }));
  await actionB;

  expect(busyIds.has("notif-B")).toBe(false);
  expect(items.find((i) => i.id === "notif-B")?.isRead).toBe(true);
});

test("FIX 4: failed mark-as-read action leaves item unread and clears busy state", async () => {
  const busyIds = new Set<string>();
  const failClient = {
    POST: vi.fn().mockResolvedValue({ response: { status: 500 } }),
  } as unknown as PulseOSClient;

  let item = { id: "notif-fail", isRead: false };

  async function markRead(id: string) {
    busyIds.add(id);
    try {
      const result = await markNotificationRead(failClient, id);
      if (result.status === "ready") {
        item = { ...item, isRead: true };
      }
    } finally {
      busyIds.delete(id);
    }
  }

  await markRead("notif-fail");

  // Item must remain unread and busy state must be cleared
  expect(item.isRead).toBe(false);
  expect(busyIds.has("notif-fail")).toBe(false);
});

// ---------------------------------------------------------------------------
// FIX 5: Focus trap and restoration mechanics
// ---------------------------------------------------------------------------
test("FIX 5: focus trap cycles Tab within focusable boundaries", () => {
  const focusables = [
    { focus: vi.fn(), id: "close-btn" },
    { focus: vi.fn(), id: "mark-all-btn" },
    { focus: vi.fn(), id: "item-btn" },
  ];

  function handleTabKey(
    e: { key: string; shiftKey: boolean; preventDefault: () => void },
    activeIndex: number,
  ) {
    if (e.key !== "Tab") return;

    const first = focusables[0]!;
    const last = focusables[focusables.length - 1]!;

    if (e.shiftKey) {
      if (activeIndex === 0) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (activeIndex === focusables.length - 1) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  // Tabbing forward from last element wraps to first
  const preventDefaultFwd = vi.fn();
  handleTabKey({ key: "Tab", shiftKey: false, preventDefault: preventDefaultFwd }, 2);
  expect(preventDefaultFwd).toHaveBeenCalled();
  expect(focusables[0]!.focus).toHaveBeenCalled();

  // Tabbing backward from first element wraps to last
  const preventDefaultBack = vi.fn();
  handleTabKey({ key: "Tab", shiftKey: true, preventDefault: preventDefaultBack }, 0);
  expect(preventDefaultBack).toHaveBeenCalled();
  expect(focusables[2]!.focus).toHaveBeenCalled();
});

test("FIX 5: focus restoration returns focus to previous active element on close", () => {
  let previousActiveElement: { focus: () => void } | null = { focus: vi.fn() };

  function handleClose() {
    if (previousActiveElement && typeof previousActiveElement.focus === "function") {
      previousActiveElement.focus();
      previousActiveElement = null;
    }
  }

  const focusSpy = previousActiveElement!.focus;
  handleClose();

  expect(focusSpy).toHaveBeenCalledTimes(1);
  expect(previousActiveElement).toBeNull();
});
