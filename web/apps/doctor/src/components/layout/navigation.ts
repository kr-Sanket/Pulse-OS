// One source of truth for the doctor portal's navigation: the sidebar renders the items and
// the top bar derives the page title, so a new page is a single edit here.

import { LayoutDashboard, Search, type LucideIcon } from "lucide-react";

export interface NavItem {
  /** Route path, matched exactly for "/" and by prefix otherwise. */
  to: string;
  label: string;
  /** Heading shown in the top bar while this route is active. */
  title: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", label: "Dashboard", title: "Dashboard", icon: LayoutDashboard },
  { to: "/patients", label: "Find a Patient", title: "Find a patient", icon: Search },
];

/** The top bar's page title for a pathname; falls back to the portal name. */
export function titleForPath(pathname: string): string {
  const match = NAV_ITEMS.filter(
    (item) => item.to !== "/" && pathname.startsWith(item.to),
  ).reduce<NavItem | null>(
    (longest, item) => (longest === null || item.to.length > longest.to.length ? item : longest),
    null,
  );
  if (match !== null) {
    return match.title;
  }
  return pathname === "/" ? "Dashboard" : "Doctor portal";
}
