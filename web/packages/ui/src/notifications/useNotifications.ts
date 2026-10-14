// React hook for Notifications state, polling, and lifecycle management (ADR-031).
//
// Hardened features:
// - Scoped to authenticated user identity (uid) with state reset & stale-response dropping
// - Safe in-flight guard preventing duplicate refresh requests on rapid focus/visibility events
// - AbortSignal cancellation on unmount and account changes without spurious error states
// - Concurrent-safe mark-as-read using a Set of busy notification IDs
// - Unread count polling every 30s while authenticated; clean teardown of timers & listeners

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PulseOSClient } from "@pulseos/api-client";

import { useAuth } from "../auth/AuthContext";
import {
  fetchUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationItem,
} from "./api";
import { badgeCountLabel, toNotificationViewItem, type NotificationViewItem } from "./view";

export interface UseNotificationsOptions {
  client: PulseOSClient;
  /** Polling interval in ms. Defaults to 30,000 (30 seconds). */
  pollIntervalMs?: number;
  /** Explicit authentication override. When omitted, derives from useAuth().user !== null. */
  enabled?: boolean;
  /** Explicit user identity override (e.g. user.uid). When omitted, derives from useAuth().user?.uid. */
  userId?: string | null;
}

export interface NotificationsState {
  unreadCount: number;
  badgeLabel: string | null;
  unreadStatus: "idle" | "loading" | "ready" | "error";
  unreadError: string | null;

  items: readonly NotificationViewItem[];
  rawItems: readonly NotificationItem[];
  listStatus: "idle" | "loading" | "ready" | "error";
  listError: string | null;

  isOpen: boolean;
  openDrawer: () => void;
  closeDrawer: () => void;
  toggleDrawer: () => void;

  busyReadIds: ReadonlySet<string>;
  markingReadId: string | null;
  markingAllRead: boolean;
  actionError: string | null;

  markRead: (id: string, signal?: AbortSignal) => Promise<void>;
  markAllRead: (signal?: AbortSignal) => Promise<void>;
  reloadList: () => Promise<void>;
  refreshUnread: () => Promise<void>;
}

const DEFAULT_POLL_INTERVAL_MS = 30_000;

export function useNotifications({
  client,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  enabled,
  userId,
}: UseNotificationsOptions): NotificationsState {
  const { user } = useAuth();
  const activeUserId = userId !== undefined ? userId : (user?.uid ?? null);
  const isAuthed = enabled !== undefined ? enabled : activeUserId !== null;

  const currentUserIdRef = useRef<string | null>(activeUserId);
  const inFlightUnreadRef = useRef(false);
  const inFlightListRef = useRef(false);
  const pollAbortControllerRef = useRef<AbortController | null>(null);
  const listAbortControllerRef = useRef<AbortController | null>(null);

  const [unreadCount, setUnreadCount] = useState(0);
  const [unreadStatus, setUnreadStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [unreadError, setUnreadError] = useState<string | null>(null);

  const [rawItems, setRawItems] = useState<readonly NotificationItem[]>([]);
  const [listStatus, setListStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [listError, setListError] = useState<string | null>(null);

  const [isOpen, setIsOpen] = useState(false);
  const [busyReadIds, setBusyReadIds] = useState<ReadonlySet<string>>(new Set());
  const [markingAllRead, setMarkingAllRead] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // In-flight guarded fetch for unread count
  const fetchUnread = useCallback(
    async (signal?: AbortSignal) => {
      if (!isAuthed || inFlightUnreadRef.current) {
        return;
      }
      inFlightUnreadRef.current = true;
      try {
        const result = await fetchUnreadCount(client, signal);
        if (signal?.aborted || currentUserIdRef.current !== activeUserId) {
          return;
        }
        if (result.status === "ready") {
          setUnreadCount(result.data.count);
          setUnreadStatus("ready");
          setUnreadError(null);
        } else {
          setUnreadStatus("error");
          setUnreadError(result.message);
        }
      } finally {
        inFlightUnreadRef.current = false;
      }
    },
    [client, isAuthed, activeUserId],
  );

  // In-flight guarded fetch for notification list
  const fetchList = useCallback(
    async (signal?: AbortSignal) => {
      if (!isAuthed || inFlightListRef.current) {
        return;
      }
      inFlightListRef.current = true;
      setListStatus("loading");
      setListError(null);
      try {
        const result = await listNotifications(client, undefined, signal);
        if (signal?.aborted || currentUserIdRef.current !== activeUserId) {
          return;
        }
        if (result.status === "ready") {
          setRawItems(result.data.items);
          setListStatus("ready");
          setListError(null);
        } else {
          setListStatus("error");
          setListError(result.message);
        }
      } finally {
        inFlightListRef.current = false;
      }
    },
    [client, isAuthed, activeUserId],
  );

  // Identity change and polling lifecycle
  useEffect(() => {
    currentUserIdRef.current = activeUserId;
    inFlightUnreadRef.current = false;
    inFlightListRef.current = false;
    pollAbortControllerRef.current?.abort();

    // Reset all notification state when identity changes or signs out
    setUnreadCount(0);
    setUnreadStatus(isAuthed ? "loading" : "idle");
    setUnreadError(null);
    setRawItems([]);
    setListStatus("idle");
    setListError(null);
    setBusyReadIds(new Set());
    setMarkingAllRead(false);
    setActionError(null);

    if (!isAuthed) {
      return;
    }

    const controller = new AbortController();
    pollAbortControllerRef.current = controller;

    void fetchUnread(controller.signal);

    const intervalId = setInterval(() => {
      void fetchUnread(controller.signal);
    }, pollIntervalMs);

    const onFocus = () => {
      void fetchUnread(controller.signal);
    };

    const onVisibilityChange = () => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        void fetchUnread(controller.signal);
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("focus", onFocus);
    }
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    return () => {
      controller.abort();
      clearInterval(intervalId);
      if (typeof window !== "undefined") {
        window.removeEventListener("focus", onFocus);
      }
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
  }, [activeUserId, isAuthed, pollIntervalMs, fetchUnread]);

  // Load notifications list when drawer opens
  useEffect(() => {
    if (isOpen && isAuthed) {
      listAbortControllerRef.current?.abort();
      const controller = new AbortController();
      listAbortControllerRef.current = controller;
      void fetchList(controller.signal);
      return () => {
        controller.abort();
      };
    }
  }, [isOpen, isAuthed, fetchList]);

  // Mark a single notification read (race-safe per-ID busy tracking)
  const markRead = useCallback(
    async (id: string, signal?: AbortSignal) => {
      setBusyReadIds((prev) => new Set(prev).add(id));
      setActionError(null);
      try {
        const result = await markNotificationRead(client, id, signal);
        if (signal?.aborted || currentUserIdRef.current !== activeUserId) {
          return;
        }
        if (result.status === "ready") {
          setRawItems((current) =>
            current.map((item) => (item.id === id ? { ...item, isRead: true } : item)),
          );
          void fetchUnread(signal);
        } else {
          setActionError(result.message);
        }
      } finally {
        setBusyReadIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [client, fetchUnread, activeUserId],
  );

  // Mark all unread notifications read (server-first, no optimistic updates)
  const markAllRead = useCallback(
    async (signal?: AbortSignal) => {
      setMarkingAllRead(true);
      setActionError(null);
      try {
        const result = await markAllNotificationsRead(client, signal);
        if (signal?.aborted || currentUserIdRef.current !== activeUserId) {
          return;
        }
        if (result.status === "ready") {
          setRawItems((current) => current.map((item) => ({ ...item, isRead: true })));
          setUnreadCount(0);
        } else {
          setActionError(result.message);
        }
      } finally {
        setMarkingAllRead(false);
      }
    },
    [client, activeUserId],
  );

  const items = useMemo(() => rawItems.map((item) => toNotificationViewItem(item)), [rawItems]);

  const badgeLabel = useMemo(() => badgeCountLabel(unreadCount), [unreadCount]);

  const markingReadId = useMemo(
    () => (busyReadIds.size > 0 ? (Array.from(busyReadIds)[0] ?? null) : null),
    [busyReadIds],
  );

  return {
    unreadCount,
    badgeLabel,
    unreadStatus,
    unreadError,

    items,
    rawItems,
    listStatus,
    listError,

    isOpen,
    openDrawer: () => setIsOpen(true),
    closeDrawer: () => setIsOpen(false),
    toggleDrawer: () => setIsOpen((prev) => !prev),

    busyReadIds,
    markingReadId,
    markingAllRead,
    actionError,

    markRead,
    markAllRead,
    reloadList: useCallback(() => fetchList(), [fetchList]),
    refreshUnread: useCallback(() => fetchUnread(), [fetchUnread]),
  };
}
