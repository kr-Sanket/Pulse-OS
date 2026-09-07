import { expect, test } from "vitest";

import { NAV_ITEMS, NAV_SECTIONS, navSectionId, titleForPath } from "./navigation";

test("navigation is grouped into Clinical and Account, in that order", () => {
  expect(NAV_SECTIONS.map((section) => section.title)).toEqual(["Clinical", "Account"]);
  expect(NAV_ITEMS.map((item) => item.label)).toEqual([
    "Dashboard",
    "Doctors",
    "Upload a Record",
    "Uploaded Records",
    "My Hospital",
    "Audit History",
  ]);
});

test("every navigable item points at a route the router serves", () => {
  // Guards the failure this file exists to catch: a sidebar entry whose path falls through
  // to the catch-all redirect, which looks like a dead link to the administrator.
  expect(NAV_ITEMS.map((item) => item.to)).toEqual([
    "/",
    "/doctors",
    "/upload",
    "/uploads",
    "/hospital",
    "/audit",
  ]);
});

test("section ids are stable and safe to use as DOM ids", () => {
  expect(navSectionId("Clinical")).toBe("nav-section-clinical");
  expect(navSectionId("My Account")).toBe("nav-section-my-account");
});

test("the top bar names the active page", () => {
  expect(titleForPath("/")).toBe("Dashboard");
  expect(titleForPath("/doctors")).toBe("Doctors");
  expect(titleForPath("/upload")).toBe("Upload a record");
  expect(titleForPath("/uploads")).toBe("Uploaded records");
  expect(titleForPath("/hospital")).toBe("Your hospital");
  expect(titleForPath("/audit")).toBe("Audit history");
});

test("a sub-path is titled by the section it sits under, not by the root", () => {
  expect(titleForPath("/hospital/doctors")).toBe("Your hospital");
  // "/uploads/:recordId" must be titled by "/uploads", not by the shorter "/upload" that
  // also prefixes it — longest prefix wins, and this is the case that proves it.
  expect(titleForPath("/uploads/rec-1")).toBe("Uploaded records");
});

test("an unknown path falls back to the portal name rather than mislabelling a page", () => {
  expect(titleForPath("/nowhere")).toBe("Hospital portal");
});
