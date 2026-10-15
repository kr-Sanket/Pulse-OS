import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "./LoginPage";

let mockUser: { displayName: string; email: string } | null = null;
let mockInitializing = false;
let mockLocationState: { from?: unknown } | null = null;

vi.mock("@pulseos/ui", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@pulseos/ui");
  return {
    ...actual,
    useAuth: () => ({
      user: mockUser,
      initializing: mockInitializing,
    }),
    useSignIn: () => ({
      busy: false,
      error: null,
      start: vi.fn(),
    }),
  };
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("react-router-dom");
  return {
    ...actual,
    useLocation: () => ({
      pathname: "/login",
      search: "",
      hash: "",
      state: mockLocationState,
      key: "default",
    }),
    Navigate: ({ to }: { to: string }) => <div data-testid="navigate-target" data-to={to} />,
  };
});

describe("LoginPage", () => {
  beforeEach(() => {
    mockUser = null;
    mockInitializing = false;
    mockLocationState = null;
  });

  it("renders login button when unauthenticated", () => {
    const html = renderToString(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Hospital portal");
    expect(html).toContain("Continue with Google");
  });

  it("shows loading screen while session is initializing", () => {
    mockInitializing = true;

    const html = renderToString(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Checking your session…");
  });

  it("shows loading screen while authenticated user's role is resolving", () => {
    mockUser = { displayName: "Hospital Admin", email: "admin@hospital.org" };

    const html = renderToString(
      <MemoryRouter>
        <LoginPage
          useRole={() => ({
            role: null,
            loading: true,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain("Checking your session…");
    expect(html).not.toContain('data-testid="navigate-target"');
  });

  it("redirects authenticated hospital user to '/' by default when no prior location state exists", () => {
    mockUser = { displayName: "Hospital Admin", email: "admin@hospital.org" };

    const html = renderToString(
      <MemoryRouter>
        <LoginPage
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
  });

  it("redirects authenticated SYSTEM_ADMIN to '/admin' by default when no prior location state exists", () => {
    mockUser = { displayName: "System Admin", email: "sysadmin@pulseos.org" };

    const html = renderToString(
      <MemoryRouter>
        <LoginPage
          useRole={() => ({
            role: "SYSTEM_ADMIN",
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate-target"');
    expect(html).toContain('data-to="/admin"');
  });

  it("redirects authenticated user to preserved location state from ProtectedRoute", () => {
    mockUser = { displayName: "System Admin", email: "sysadmin@pulseos.org" };
    mockLocationState = { from: { pathname: "/admin/verification" } };

    const html = renderToString(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate-target"');
    expect(html).toContain('data-to="/admin/verification"');
  });

  it("safely falls back to '/' when location state contains an open redirect attack", () => {
    mockUser = { displayName: "Admin", email: "admin@hospital.org" };
    mockLocationState = { from: "https://malicious-external-site.com" };

    const html = renderToString(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate-target"');
    expect(html).toContain('data-to="/"');
  });
});
