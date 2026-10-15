import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AdminLayout } from "./AdminLayout";

vi.mock("@pulseos/ui", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@pulseos/ui");
  return {
    ...actual,
    useAuth: () => ({
      user: { displayName: "Platform Admin", email: "sysadmin@pulseos.org" },
      signOutUser: vi.fn(),
    }),
    LoadingScreen: ({ message }: { message: string }) => (
      <div data-testid="loading-screen">{message}</div>
    ),
  };
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("react-router-dom");
  return {
    ...actual,
    Navigate: ({ to }: { to: string }) => <div data-testid="navigate-target" data-to={to} />,
    Outlet: () => <div data-testid="outlet-content">Admin Outlet Content</div>,
  };
});

describe("AdminLayout", () => {
  it("renders admin content and navigation when role is confirmed as SYSTEM_ADMIN", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminLayout
          useRole={() => ({
            role: "SYSTEM_ADMIN",
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain("PulseOS");
    expect(html).toContain("System Admin");
    expect(html).toContain("Hospital Verification");
    expect(html).toContain('data-testid="outlet-content"');
    expect(html).not.toContain('data-testid="navigate-target"');
  });

  it("fails closed and redirects hospital users away from admin interface", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminLayout
          useRole={() => ({
            role: "HOSPITAL_ADMIN",
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate-target"');
    expect(html).toContain('data-to="/"');
    expect(html).not.toContain('data-testid="outlet-content"');
    expect(html).not.toContain("Hospital Verification");
  });

  it("fails closed when user has no role or is unprovisioned", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminLayout
          useRole={() => ({
            role: null,
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate-target"');
    expect(html).toContain('data-to="/"');
    expect(html).not.toContain('data-testid="outlet-content"');
  });

  it("shows loading screen and does not expose admin content while role is loading", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminLayout
          useRole={() => ({
            role: null,
            loading: true,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain("Verifying administrative access…");
    expect(html).not.toContain('data-testid="outlet-content"');
    expect(html).not.toContain("Hospital Verification");
    expect(html).not.toContain('data-testid="navigate-target"');
  });
});
