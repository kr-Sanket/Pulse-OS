// Off-canvas slide-over notification drawer (ADR-031).
//
// Hardened accessibility:
// - Keeps keyboard focus within the modal drawer while it is open (Tab cycles through controls)
// - Returns focus to the bell trigger element when the drawer closes
// - Escape key dismisses drawer; backdrop click dismisses drawer
// - Concurrent-safe mark-as-read using busyReadIds Set
// - Loading skeletons, empty state, and error banner with retry

import { useEffect, useRef } from "react";
import { Portal } from "radix-ui";
import { AlertCircle, Bell, Check, Inbox, RotateCcw, X } from "lucide-react";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import { cn } from "../lib/utils";
import type { NotificationsState } from "./useNotifications";
import {
  MARK_ALL_READ_LABEL,
  NO_NOTIFICATIONS_DESC,
  NO_NOTIFICATIONS_TITLE,
  NOTIFICATIONS_TITLE,
} from "./view";

export interface NotificationDrawerProps {
  open: boolean;
  onClose: () => void;
  notifications: NotificationsState;
}

export function NotificationDrawer({ open, onClose, notifications }: NotificationDrawerProps) {
  const {
    items,
    unreadCount,
    listStatus,
    listError,
    actionError,
    busyReadIds,
    markingAllRead,
    markRead,
    markAllRead,
    reloadList,
  } = notifications;

  const panelRef = useRef<HTMLElement | null>(null);
  const previousActiveElementRef = useRef<HTMLElement | null>(null);

  // Focus trap and focus restoration on open / close
  useEffect(() => {
    if (!open) {
      if (
        previousActiveElementRef.current &&
        typeof previousActiveElementRef.current.focus === "function"
      ) {
        previousActiveElementRef.current.focus();
        previousActiveElementRef.current = null;
      }
      return;
    }

    if (typeof document !== "undefined") {
      previousActiveElementRef.current = document.activeElement as HTMLElement | null;
    }

    // Set initial focus to the first focusable control inside the drawer
    const focusTimer = setTimeout(() => {
      if (!panelRef.current) {
        return;
      }
      const focusables = panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      const firstFocusable = focusables[0];
      if (firstFocusable) {
        firstFocusable.focus();
      }
    }, 0);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }

      if (e.key === "Tab" && panelRef.current) {
        const focusables = Array.from(
          panelRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
          ),
        );
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (!first || !last) {
          e.preventDefault();
          return;
        }

        if (e.shiftKey) {
          if (
            document.activeElement === first ||
            !panelRef.current.contains(document.activeElement)
          ) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (
            document.activeElement === last ||
            !panelRef.current.contains(document.activeElement)
          ) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
    }

    return () => {
      clearTimeout(focusTimer);
      if (typeof window !== "undefined") {
        window.removeEventListener("keydown", handleKeyDown);
      }
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <Portal.Root>
      <div className="fixed inset-0 z-50 flex justify-end">
        {/* Backdrop Scrim */}
        <button
          type="button"
          className="bg-foreground/40 fixed inset-0 z-40 backdrop-blur-xs transition-opacity duration-150"
          aria-label="Close notifications drawer"
          onClick={onClose}
        />

        {/* Slide-over Drawer Panel with Focus Trap Ref */}
        <aside
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={NOTIFICATIONS_TITLE}
          className="bg-background border-border relative z-50 flex h-full max-h-screen w-full max-w-md flex-col border-l shadow-2xl transition-transform duration-200 outline-none"
          tabIndex={-1}
        >
          {/* Drawer Header */}
          <div className="border-border/70 flex h-16 shrink-0 items-center justify-between border-b px-5">
            <div className="flex items-center gap-2">
              <Bell className="text-primary size-5" aria-hidden />
              <h2 className="text-base font-semibold tracking-tight">{NOTIFICATIONS_TITLE}</h2>
              {unreadCount > 0 ? (
                <Badge variant="primary" className="text-xs">
                  {unreadCount} unread
                </Badge>
              ) : null}
            </div>

            <div className="flex items-center gap-2">
              {unreadCount > 0 ? (
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => void markAllRead()}
                  disabled={markingAllRead}
                  className="text-muted-foreground hover:text-foreground text-xs"
                >
                  {markingAllRead ? "Marking…" : MARK_ALL_READ_LABEL}
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onClose}
                aria-label="Close notifications"
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
          </div>

          {/* Action Error Banner */}
          {actionError ? (
            <div className="bg-destructive/10 text-destructive border-destructive/20 flex items-center gap-2 border-b px-5 py-2.5 text-xs">
              <AlertCircle className="size-4 shrink-0" aria-hidden />
              <span className="flex-1">{actionError}</span>
            </div>
          ) : null}

          {/* Drawer Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {listStatus === "loading" && items.length === 0 ? (
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="border-border/60 rounded-xl border p-4 space-y-2">
                    <div className="flex items-center justify-between">
                      <Skeleton className="h-4 w-24" />
                      <Skeleton className="h-3 w-16" />
                    </div>
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-full" />
                  </div>
                ))}
              </div>
            ) : listStatus === "error" && items.length === 0 ? (
              <div className="border-destructive/20 bg-destructive/5 rounded-xl border p-6 text-center space-y-3">
                <AlertCircle className="text-destructive mx-auto size-8" aria-hidden />
                <p className="text-foreground text-sm font-medium">Failed to load notifications</p>
                <p className="text-muted-foreground text-xs">{listError}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void reloadList()}
                  className="gap-1.5"
                >
                  <RotateCcw className="size-3.5" aria-hidden />
                  Retry
                </Button>
              </div>
            ) : items.length === 0 ? (
              <div className="flex h-64 flex-col items-center justify-center text-center p-6 space-y-3">
                <div className="bg-muted flex size-12 items-center justify-center rounded-full">
                  <Inbox className="text-muted-foreground size-6" aria-hidden />
                </div>
                <p className="text-foreground text-sm font-medium">{NO_NOTIFICATIONS_TITLE}</p>
                <p className="text-muted-foreground text-xs leading-relaxed max-w-xs">
                  {NO_NOTIFICATIONS_DESC}
                </p>
              </div>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  className={cn(
                    "border-border/60 transition-colors relative rounded-xl border p-3.5 space-y-2",
                    !item.isRead ? "bg-primary/5 border-primary/20" : "bg-card hover:bg-muted/30",
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {!item.isRead ? (
                        <span
                          className="bg-primary size-2 shrink-0 rounded-full"
                          aria-label="Unread"
                        />
                      ) : null}
                      <Badge variant={item.meta.badgeVariant} className="text-[11px] px-1.5 py-0">
                        {item.meta.label}
                      </Badge>
                    </div>
                    <span className="text-muted-foreground shrink-0 text-[11px]">
                      {item.timeAgo}
                    </span>
                  </div>

                  <div className="space-y-1">
                    <h3
                      className={cn(
                        "text-sm leading-snug",
                        !item.isRead
                          ? "font-semibold text-foreground"
                          : "font-medium text-foreground/90",
                      )}
                    >
                      {item.title}
                    </h3>
                    <p className="text-muted-foreground text-xs leading-relaxed">{item.message}</p>
                  </div>

                  {!item.isRead ? (
                    <div className="flex justify-end pt-1">
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => void markRead(item.id)}
                        disabled={busyReadIds.has(item.id)}
                        className="text-muted-foreground hover:text-foreground gap-1 text-[11px]"
                      >
                        <Check className="size-3" aria-hidden />
                        {busyReadIds.has(item.id) ? "Marking…" : "Mark as read"}
                      </Button>
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </Portal.Root>
  );
}
