// One source of truth for the hospital portal's navigation: the sidebar renders the sections
// and the top bar derives the page title, so a new page is a single edit here.
//
// Grouped rather than flat, matching the other two portals: each group's list is associated
// with its heading via aria-labelledby, so the grouping reaches assistive technology and is
// not merely visual.
//
// Only what the portal actually routes to.

import {
  Building2,
  FolderOpen,
  LayoutDashboard,
  Stethoscope,
  Upload,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  /** Route path, matched exactly for "/" and by prefix otherwise. */
  to: string;
  label: string;
  /** Heading shown in the top bar while this route is active. */
  title: string;
  icon: LucideIcon;
}

export interface NavSection {
  /** Rendered uppercase as the group heading. */
  title: string;
  items: readonly NavItem[];
}

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    title: "Clinical",
    items: [
      { to: "/", label: "Dashboard", title: "Dashboard", icon: LayoutDashboard },
      // No count badge on the pending doctors: there is no aggregate endpoint, and a live
      // count would mean the layout fetching the roster on every route.
      { to: "/doctors", label: "Doctors", title: "Doctors", icon: Stethoscope },
      { to: "/upload", label: "Upload a Record", title: "Upload a record", icon: Upload },
      // No count badge: there is no aggregate endpoint, and a live count would mean the
      // layout fetching the listing on every route.
      { to: "/uploads", label: "Uploaded Records", title: "Uploaded records", icon: FolderOpen },
    ],
  },
  {
    title: "Account",
    items: [{ to: "/hospital", label: "My Hospital", title: "Your hospital", icon: Building2 }],
  },
];

/** Every navigable item, flattened — the order the sections declare them in. */
export const NAV_ITEMS: readonly NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

/** A stable DOM id for a section heading, so its list can reference it. */
export function navSectionId(title: string): string {
  return `nav-section-${title.toLowerCase().replace(/\s+/g, "-")}`;
}

/** The top bar's page title for a pathname; falls back to the portal name.
 *
 * Longest-prefix wins so that a future sub-page under an existing section is titled by that
 * section rather than by whichever entry happens to be declared first. "/" is excluded from
 * the prefix match because it prefixes everything. */
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
  return pathname === "/" ? "Dashboard" : "Hospital portal";
}
