// Sidebar navigation. Always visible from md upwards; below that it is an off-canvas
// drawer driven by PatientLayout, which owns the open/closed state.
//
// Grouped into labelled sections (Overview / Data Sharing / Account). Each group's list is
// associated with its heading via aria-labelledby, so the grouping reaches assistive
// technology and is not merely visual. Sections are separated by whitespace rather than
// rules; the only divider is above the footer.

import { HeartPulse, LogOut } from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { initialsFor } from "./initials";
import { NAV_SECTIONS, navSectionId } from "./navigation";

export interface SidebarProps {
  /** Drawer state on small screens; ignored from md upwards. */
  open: boolean;
  /** Called after a navigation choice so the drawer closes behind the user. */
  onNavigate: () => void;
}

export function Sidebar({ open, onNavigate }: SidebarProps) {
  const { user, signOutUser } = useAuth();
  const displayName = user?.displayName ?? null;
  const email = user?.email ?? null;
  const photoURL = user?.photoURL ?? null;

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
        <span className="text-[17px] font-semibold tracking-tight">PulseOS</span>
      </div>

      <nav className="flex-1 space-y-8 overflow-y-auto px-3 pb-2">
        {NAV_SECTIONS.map((section) => {
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
                          "group flex items-center gap-3.5 rounded-xl px-3.5 py-2.5 text-sm font-medium transition-colors duration-150",
                          isActive
                            ? "bg-sidebar-accent text-sidebar-accent-foreground"
                            : "text-muted-foreground hover:bg-accent hover:text-foreground",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <item.icon
                            className={cn("size-[18px] shrink-0", isActive && "text-primary")}
                            strokeWidth={isActive ? 2.4 : 2}
                            aria-hidden
                          />
                          <span className="flex-1 truncate">{item.label}</span>
                          {item.badge === undefined ? null : (
                            <span className="bg-primary-muted text-primary flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1.5 text-[10px] font-medium tabular-nums">
                              {item.badge}
                            </span>
                          )}
                        </>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="border-sidebar-border shrink-0 space-y-1 border-t px-3 pt-4 pb-5">
        <div className="flex items-center gap-3 px-2 py-1.5">
          <Avatar className="size-9">
            {photoURL === null ? null : <AvatarImage src={photoURL} alt="" />}
            <AvatarFallback className="text-xs">{initialsFor(displayName, email)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{displayName ?? "Signed in"}</p>
            {email === null ? null : (
              <p className="text-muted-foreground truncate text-xs">{email}</p>
            )}
          </div>
        </div>
        <Button
          variant="ghost"
          className="text-muted-foreground hover:text-foreground w-full justify-start gap-3.5 rounded-xl px-3.5"
          onClick={() => void signOutUser()}
        >
          <LogOut className="size-[18px]" aria-hidden />
          Sign out
        </Button>
      </div>
    </aside>
  );
}
