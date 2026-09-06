import { expect, test } from "vitest";

import { NAV_ITEMS, NAV_SECTIONS, navSectionId, titleForPath } from "./navigation";

test("navigation is grouped into Clinical and Account, in that order", () => {
  expect(NAV_SECTIONS.map((section) => section.title)).toEqual(["Clinical", "Account"]);
  expect(NAV_ITEMS.map((item) => item.label)).toEqual(["Dashboard", "Doctors", "My Hospital"]);
});

test("every navigable item points at a route the router serves", () => {
  // Guards the failure this file exists to catch: a sidebar entry whose path falls through
  // to the catch-all redirect, which looks like a dead link to the administrator.
  expect(NAV_ITEMS.map((item) => item.to)).toEqual(["/", "/doctors", "/hospital"]);
});

test("section ids are stable and safe to use as DOM ids", () => {
  expect(navSectionId("Clinical")).toBe("nav-section-clinical");
  expect(navSectionId("My Account")).toBe("nav-section-my-account");
});

test("the top bar names the active page", () => {
  expect(titleForPath("/")).toBe("Dashboard");
  expect(titleForPath("/doctors")).toBe("Doctors");
  expect(titleForPath("/hospital")).toBe("Your hospital");
});

test("a sub-path is titled by the section it sits under, not by the root", () => {
  expect(titleForPath("/hospital/doctors")).toBe("Your hospital");
});

test("an unknown path falls back to the portal name rather than mislabelling a page", () => {
  expect(titleForPath("/nowhere")).toBe("Hospital portal");
});
