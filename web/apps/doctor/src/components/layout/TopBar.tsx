// Top header: the menu toggle on small screens and the active page title. Deliberately
// carries no user identity — the sidebar footer is the single account area.

import { Menu } from "lucide-react";
import { useLocation } from "react-router-dom";

import { Button, NotificationBell } from "@pulseos/ui";
import { api } from "@/api";

import { titleForPath } from "./navigation";

export interface TopBarProps {
  /** Opens the sidebar drawer on small screens. */
  onMenuClick: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const { pathname } = useLocation();

  return (
    <header className="bg-background/95 border-border/60 sticky top-0 z-20 border-b backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-4 md:px-8">
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={onMenuClick}
          aria-label="Open navigation"
        >
          <Menu className="size-5" aria-hidden />
        </Button>
        <span className="font-semibold tracking-tight md:hidden">PulseOS</span>
        <h1 className="min-w-0 flex-1 truncate text-[15px] font-medium md:text-base">
          {titleForPath(pathname)}
        </h1>

        <div className="flex shrink-0 items-center gap-3">
          <NotificationBell client={api} />
        </div>
      </div>
    </header>
  );
}
