// Dedicated sidebar navigation for the PulseOS System Admin interface.
//
// Shows only administrative navigation items (Dashboard and Hospital Verification).
// Never displays hospital-specific routes (Clinical, Doctors, Upload, etc.).
// Includes clear System Admin branding and an account footer with a logout action.

import { LayoutDashboard, LogOut, ShieldCheck } from "lucide-react";
import { NavLink } from "react-router-dom";

import {
  Avatar,
  AvatarFallback,
  AvatarImage,
  Badge,
  Button,
  cn,
  initialsFor,
  Separator,
  useAuth,
} from "@pulseos/ui";

export interface AdminSidebarProps {
  open: boolean;
  onNavigate: () => void;
}

export const ADMIN_NAV_LINKS = [
  {
    to: "/admin",
    end: true,
    label: "Dashboard",
    icon: LayoutDashboard,
  },
  {
    to: "/admin/verification",
    end: false,
    label: "Hospital Verification",
    icon: ShieldCheck,
  },
] as const;

export function AdminSidebar({ open, onNavigate }: AdminSidebarProps) {
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
      aria-label="System Admin navigation"
    >
      <div className="flex shrink-0 items-center gap-3 px-5 pt-8 pb-8">
        <div className="bg-primary/10 text-primary flex size-10 items-center justify-center rounded-xl shadow-xs">
          <ShieldCheck className="size-6" aria-hidden />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="block text-[17px] leading-tight font-semibold tracking-tight">
              PulseOS
            </span>
            <Badge
              variant="outline"
              className="text-[10px] uppercase tracking-wider px-1.5 py-0 font-medium"
            >
              Admin
            </Badge>
          </div>
          <span className="text-primary text-[11px] font-semibold tracking-wider uppercase">
            System Administrator
          </span>
        </div>
      </div>

      <nav
        className="flex-1 space-y-8 overflow-y-auto px-3 pb-2"
        aria-label="Administrative sections"
      >
        <div>
          <p
            id="admin-nav-section-title"
            className="text-muted-foreground px-3.5 pb-3 text-[11px] font-medium tracking-wider uppercase"
          >
            Platform Administration
          </p>
          <ul aria-labelledby="admin-nav-section-title" className="space-y-1">
            {ADMIN_NAV_LINKS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
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
            {displayName ?? "Administrator"}
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
