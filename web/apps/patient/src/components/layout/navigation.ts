// One source of truth for the portal's navigation: the sidebar renders the sections, and
// the top bar derives the current page title from the flattened list, so a new page is a
// single edit here.
//
// Routes and icons are unchanged — grouping and labels are presentation.

import {
  FileText,
  KeyRound,
  LayoutDashboard,
  ScrollText,
  Settings,
  ShieldCheck,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  /** Route path, matched exactly for "/" and by prefix otherwise. */
  to: string;
  /** Sidebar label. */
  label: string;
  /** Heading shown in the top bar while this route is active. */
  title: string;
  icon: LucideIcon;
  /** Optional count pill. Mock-derived today; the consent API supplies it later. */
  badge?: number;
}

export interface NavSection {
  /** Rendered uppercase as the group heading. */
  title: string;
  items: readonly NavItem[];
}

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    title: "Overview",
    items: [
      { to: "/", label: "Dashboard", title: "Dashboard", icon: LayoutDashboard },
      { to: "/records", label: "My Records", title: "Medical records", icon: FileText },
    ],
  },
  {
    title: "Data Sharing",
    items: [
      // No badge: the count was mock-derived, and a live one would mean the layout
      // fetching the consent inbox on every route. The Dashboard and the Consent page
      // both show the real number.
      { to: "/consent", label: "Consent Requests", title: "Access requests", icon: ShieldCheck },
      { to: "/grants", label: "Active Grants", title: "Active grants", icon: KeyRound },
      { to: "/audit", label: "Audit History", title: "Audit log", icon: ScrollText },
    ],
  },
  {
    title: "Account",
    items: [
      { to: "/profile", label: "Profile", title: "Your profile", icon: UserRound },
      { to: "/settings", label: "Settings", title: "Settings", icon: Settings },
    ],
  },
];

/** Every navigable item, flattened — the order the sections declare them in. */
export const NAV_ITEMS: readonly NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

/** A stable DOM id for a section heading, so its list can reference it. */
export function navSectionId(title: string): string {
  return `nav-section-${title.toLowerCase().replace(/\s+/g, "-")}`;
}

/** The top bar's page title for a pathname; falls back to the app name. */
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
  return pathname === "/" ? "Dashboard" : "Patient portal";
}
