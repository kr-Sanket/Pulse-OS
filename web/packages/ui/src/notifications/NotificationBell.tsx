// Bell trigger button with dynamic unread count badge and drawer wiring (ADR-031).
//
// Mounts into the patient and doctor TopBars. When clicked, toggles the slide-over
// NotificationDrawer. Displays an unread count badge when unreadCount > 0.

import { Bell } from "lucide-react";
import type { PulseOSClient } from "@pulseos/api-client";

import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { cn } from "../lib/utils";
import { NotificationDrawer } from "./NotificationDrawer";
import { useNotifications, type UseNotificationsOptions } from "./useNotifications";

export interface NotificationBellProps extends Partial<UseNotificationsOptions> {
  client: PulseOSClient;
  className?: string;
}

export function NotificationBell({
  client,
  pollIntervalMs,
  enabled,
  className,
}: NotificationBellProps) {
  const notifications = useNotifications({ client, pollIntervalMs, enabled });
  const { unreadCount, badgeLabel, isOpen, toggleDrawer, closeDrawer } = notifications;

  return (
    <>
      <div className={cn("relative inline-flex", className)}>
        <Button
          variant="ghost"
          size="icon"
          aria-label={unreadCount > 0 ? `Notifications (${unreadCount} unread)` : "Notifications"}
          aria-haspopup="dialog"
          aria-expanded={isOpen}
          onClick={toggleDrawer}
        >
          <Bell className="size-5" aria-hidden />
          {badgeLabel !== null ? (
            <Badge
              variant="default"
              className="pointer-events-none absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none"
            >
              {badgeLabel}
            </Badge>
          ) : null}
        </Button>
      </div>

      <NotificationDrawer open={isOpen} onClose={closeDrawer} notifications={notifications} />
    </>
  );
}
