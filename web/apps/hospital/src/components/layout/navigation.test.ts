import { expect, test } from "vitest";

import {
  ADMIN_NAV_SECTION,
  NAV_ITEMS,
  NAV_SECTIONS,
  getNavSections,
  navSectionId,
  titleForPath,
} from "./navigation";

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
  expect(navSectionId("System Admin")).toBe("nav-section-system-admin");
});

test("the top bar names the active page", () => {
  expect(titleForPath("/")).toBe("Dashboard");
  expect(titleForPath("/doctors")).toBe("Doctors");
  expect(titleForPath("/upload")).toBe("Upload a record");
  expect(titleForPath("/uploads")).toBe("Uploaded records");
  expect(titleForPath("/hospital")).toBe("Your hospital");
  expect(titleForPath("/audit")).toBe("Audit history");
  expect(titleForPath("/admin/verification")).toBe("Hospital Verification");
  expect(titleForPath("/admin")).toBe("System Admin Dashboard");
});

test("a sub-path is titled by the section it sits under, not by the root", () => {
  expect(titleForPath("/hospital/doctors")).toBe("Your hospital");
  // "/uploads/:recordId" must be titled by "/uploads", not by the shorter "/upload" that
  // also prefixes it — longest prefix wins, and this is the case that proves it.
  expect(titleForPath("/uploads/rec-1")).toBe("Uploaded records");
  expect(titleForPath("/admin/verification/HID-0001")).toBe("Hospital Verification");
});

test("an unknown path falls back to the portal name rather than mislabelling a page", () => {
  expect(titleForPath("/nowhere")).toBe("Hospital portal");
});

test("role-aware navigation exposes System Admin section only for SYSTEM_ADMIN", () => {
  // 1. SYSTEM_ADMIN role gets standard hospital navigation PLUS System Admin section
  const adminSections = getNavSections("SYSTEM_ADMIN");
  expect(adminSections.map((s) => s.title)).toEqual(["Clinical", "Account", "System Admin"]);
  const adminItems = adminSections.flatMap((s) => s.items);
  expect(adminItems.some((item) => item.to === "/admin/verification")).toBe(true);

  // 2. HOSPITAL_ADMIN role gets only standard hospital navigation
  const hospitalAdminSections = getNavSections("HOSPITAL_ADMIN");
  expect(hospitalAdminSections.map((s) => s.title)).toEqual(["Clinical", "Account"]);
  expect(
    hospitalAdminSections.flatMap((s) => s.items).some((item) => item.to === "/admin/verification"),
  ).toBe(false);

  // 3. Null/unauthenticated role gets only standard hospital navigation
  const unauthSections = getNavSections(null);
  expect(unauthSections.map((s) => s.title)).toEqual(["Clinical", "Account"]);
  expect(
    unauthSections.flatMap((s) => s.items).some((item) => item.to === "/admin/verification"),
  ).toBe(false);

  // 4. Other roles (e.g. DOCTOR, PATIENT) do not see the admin section
  expect(getNavSections("DOCTOR").map((s) => s.title)).toEqual(["Clinical", "Account"]);
  expect(getNavSections("PATIENT").map((s) => s.title)).toEqual(["Clinical", "Account"]);
});

test("ADMIN_NAV_SECTION points to the registered hospital verification route", () => {
  expect(ADMIN_NAV_SECTION.items[0]).toMatchObject({
    to: "/admin/verification",
    label: "Hospital Verification",
    title: "Hospital Verification",
  });
});
