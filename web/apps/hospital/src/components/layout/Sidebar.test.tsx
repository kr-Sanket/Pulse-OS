import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "./Sidebar";

// Mock @pulseos/ui useAuth
vi.mock("@pulseos/ui", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@pulseos/ui");
  return {
    ...actual,
    useAuth: () => ({
      user: { displayName: "Admin User", email: "admin@hospital.org" },
      signOutUser: vi.fn(),
    }),
  };
});

describe("Sidebar role-aware navigation", () => {
  it("displays System Admin section and Hospital Verification link for SYSTEM_ADMIN", () => {
    const html = renderToString(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar open={true} onNavigate={vi.fn()} role="SYSTEM_ADMIN" />
      </MemoryRouter>,
    );

    // Standard navigation
    expect(html).toContain("Clinical");
    expect(html).toContain("Dashboard");
    expect(html).toContain("Account");

    // System Admin section is visible
    expect(html).toContain("System Admin");
    expect(html).toContain("Hospital Verification");
    expect(html).toContain('href="/admin/verification"');
  });

  it("does NOT display System Admin section for HOSPITAL_ADMIN", () => {
    const html = renderToString(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar open={true} onNavigate={vi.fn()} role="HOSPITAL_ADMIN" />
      </MemoryRouter>,
    );

    // Standard navigation is present
    expect(html).toContain("Dashboard");
    expect(html).toContain("Doctors");

    // System Admin is absent
    expect(html).not.toContain("System Admin");
    expect(html).not.toContain("Hospital Verification");
    expect(html).not.toContain('href="/admin/verification"');
  });

  it("does NOT display System Admin section while role loading is incomplete (role null)", () => {
    const html = renderToString(
      <MemoryRouter initialEntries={["/"]}>
        <Sidebar open={true} onNavigate={vi.fn()} role={null} />
      </MemoryRouter>,
    );

    expect(html).not.toContain("System Admin");
    expect(html).not.toContain("Hospital Verification");
    expect(html).not.toContain('href="/admin/verification"');
  });

  it("highlights active navigation item when on /admin/verification", () => {
    const html = renderToString(
      <MemoryRouter initialEntries={["/admin/verification"]}>
        <Sidebar open={true} onNavigate={vi.fn()} role="SYSTEM_ADMIN" />
      </MemoryRouter>,
    );

    expect(html).toContain('href="/admin/verification"');
    // Active class is applied by NavLink
    expect(html).toContain("bg-sidebar-accent");
  });
});
