// One source of truth for the doctor portal's navigation: the sidebar renders the sections
// and the top bar derives the page title, so a new page is a single edit here.
//
// Grouped rather than flat, matching the patient portal: each group's list is associated with
// its heading via aria-labelledby, so the grouping reaches assistive technology and is not
// merely visual.

import { ClipboardList, IdCard, LayoutDashboard, Search, type LucideIcon } from "lucide-react";

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
      { to: "/patients", label: "Find a Patient", title: "Find a patient", icon: Search },
      // No count badge: there is no aggregate endpoint, and a live count would mean the
      // layout fetching the request listing on every route.
      { to: "/requests", label: "My Requests", title: "My requests", icon: ClipboardList },
    ],
  },
  {
    title: "Account",
    items: [{ to: "/profile", label: "My Profile", title: "Your profile", icon: IdCard }],
  },
];

/** Every navigable item, flattened — the order the sections declare them in. */
export const NAV_ITEMS: readonly NavItem[] = NAV_SECTIONS.flatMap((section) => section.items);

/** A stable DOM id for a section heading, so its list can reference it. */
export function navSectionId(title: string): string {
  return `nav-section-${title.toLowerCase().replace(/\s+/g, "-")}`;
}

/** Pages reached from another page rather than from the sidebar: they need a top-bar title
 * but must not appear in the navigation, so they are matched before NAV_ITEMS — otherwise
 * the parent route's prefix would claim them and the bar would name the wrong page. */
const SUB_PAGE_TITLES: readonly { matches: (pathname: string) => boolean; title: string }[] = [
  {
    // /patients/:healthId/records — reached from Find a Patient.
    matches: (pathname) => pathname.startsWith("/patients/") && pathname.endsWith("/records"),
    title: "Granted records",
  },
  {
    // /records/:recordId — reached by selecting a granted record.
    matches: (pathname) => pathname.startsWith("/records/"),
    title: "Record",
  },
];

/** The top bar's page title for a pathname; falls back to the portal name. */
export function titleForPath(pathname: string): string {
  const subPage = SUB_PAGE_TITLES.find((page) => page.matches(pathname));
  if (subPage !== undefined) {
    return subPage.title;
  }
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
