// Top header: a lightweight page toolbar — the menu toggle on small screens, the active
// page title, a search field and notifications.
//
// Deliberately carries no user identity: the sidebar footer is the single account area, so
// repeating the avatar and name here would only duplicate it.
//
// Search and notifications are presentational only — no query state, no requests. They
// exist so the shell matches the intended product surface; wiring lands with the pages
// that own the data.

import { Menu, Search } from "lucide-react";
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
    // The header stays full-bleed so its border and backdrop span the whole width…
    <header className="bg-background/95 border-border/60 sticky top-0 z-20 border-b backdrop-blur">
      {/* …while this inner column mirrors <main>'s width and padding in PatientLayout, so
          the page title lines up with the page heading below it and the toolbar's right
          edge lines up with the content's right edge. */}
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

        {/* flex-1 makes the gap between the title and the toolbar the elastic region, so it
            absorbs all spare width instead of the toolbar drifting inward. */}
        <h1 className="min-w-0 flex-1 truncate text-[15px] font-medium md:text-base">
          {titleForPath(pathname)}
        </h1>

        {/* One right-aligned toolbar: search and notifications. shrink-0 keeps it at its
            natural width so the search field never gets compressed. */}
        <div className="flex shrink-0 items-center gap-3">
          <div className="relative hidden shrink-0 md:block">
            <Search
              className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
              aria-hidden
            />
            <input
              type="search"
              placeholder="Search records, doctors, requests…"
              aria-label="Search"
              className="border-input bg-muted/60 text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:bg-card focus-visible:ring-ring/25 h-10 w-56 rounded-xl border pr-3 pl-9 text-sm transition-colors duration-150 outline-none focus-visible:ring-[3px] lg:w-72"
            />
          </div>

          <NotificationBell client={api} />
        </div>
      </div>
    </header>
  );
}
