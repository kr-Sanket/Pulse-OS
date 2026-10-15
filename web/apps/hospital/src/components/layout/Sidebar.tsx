// Sidebar navigation. Always visible from md upwards; below that it is an off-canvas drawer
// driven by HospitalLayout, which owns the open/closed state. Same shell as the other two
// portals, with the signed-in administrator's account in the footer.
//
// The footer shows the Firebase account, not a PulseOS profile: this slice makes no API
// calls, and the hospital's own name arrives with GET /hospitals/me in the next slice.

import { HeartPulse, LogOut } from "lucide-react";
import { NavLink } from "react-router-dom";

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Button,
  cn,
  initialsFor,
  Separator,
  useAuth,
} from "@pulseos/ui";

import { getNavSections, navSectionId } from "./navigation";

export interface SidebarProps {
  open: boolean;
  onNavigate: () => void;
  role?: string | null;
}

export function Sidebar({ open, onNavigate, role = null }: SidebarProps) {
  const { user, signOutUser } = useAuth();
  const displayName = user?.displayName ?? null;
  const email = user?.email ?? null;
  const photoURL = user?.photoURL ?? null;
  const sections = getNavSections(role);

  return (
    <aside
      className={cn(
        "bg-sidebar border-sidebar-border fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r transition-transform duration-200 md:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}
      aria-label="Portal navigation"
    >
      <div className="flex shrink-0 items-center gap-2.5 px-5 pt-8 pb-8">
        <HeartPulse className="text-primary size-6" aria-hidden />
        <div className="min-w-0">
          <span className="block text-[17px] leading-tight font-semibold tracking-tight">
            PulseOS
          </span>
          <span className="text-muted-foreground text-[11px] tracking-wider uppercase">
            Hospital portal
          </span>
        </div>
      </div>

      <nav className="flex-1 space-y-8 overflow-y-auto px-3 pb-2">
        {sections.map((section) => {
          const headingId = navSectionId(section.title);
          return (
            <div key={section.title}>
              <p
                id={headingId}
                className="text-muted-foreground px-3.5 pb-3 text-[11px] font-medium tracking-wider uppercase"
              >
                {section.title}
              </p>
              <ul aria-labelledby={headingId} className="space-y-1">
                {section.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === "/"}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm transition-colors duration-150",
                          isActive
                            ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                            : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        )
                      }
                    >
                      <item.icon className="size-[18px] shrink-0" aria-hidden />
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>

      <Separator />

      <div className="flex items-center gap-3 p-4">
        <Avatar className="size-9">
          {photoURL === null ? null : <AvatarImage src={photoURL} alt="" />}
          <AvatarFallback className="text-xs font-medium">
            {initialsFor(displayName, email)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-sm font-medium">
            {displayName ?? "Signed in"}
          </p>
          <p className="text-muted-foreground truncate text-xs">{email ?? ""}</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Sign out"
          onClick={() => void signOutUser()}
        >
          <LogOut className="size-4" aria-hidden />
        </Button>
      </div>
    </aside>
  );
}
