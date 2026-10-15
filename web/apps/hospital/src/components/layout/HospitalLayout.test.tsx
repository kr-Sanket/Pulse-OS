import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { HospitalLayout } from "./HospitalLayout";

vi.mock("@pulseos/ui", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@pulseos/ui");
  return {
    ...actual,
    useAuth: () => ({
      user: { displayName: "Hospital Admin", email: "admin@hospital.org" },
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
    Outlet: () => <div data-testid="hospital-outlet">Hospital Content</div>,
  };
});

describe("HospitalLayout", () => {
  it("redirects SYSTEM_ADMIN away to /admin", () => {
    const html = renderToString(
      <MemoryRouter>
        <HospitalLayout
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
    expect(html).not.toContain('data-testid="hospital-outlet"');
  });

  it("renders hospital navigation and outlet for HOSPITAL_ADMIN", () => {
    const html = renderToString(
      <MemoryRouter>
        <HospitalLayout
          useRole={() => ({
            role: "HOSPITAL_ADMIN",
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="hospital-outlet"');
    expect(html).toContain("Dashboard");
    expect(html).toContain("Doctors");
    expect(html).not.toContain('data-testid="navigate-target"');
  });

  it("shows loading screen and does not render outlet while role is loading", () => {
    const html = renderToString(
      <MemoryRouter>
        <HospitalLayout
          useRole={() => ({
            role: null,
            loading: true,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain("Checking authorization…");
    expect(html).not.toContain('data-testid="hospital-outlet"');
    expect(html).not.toContain('data-testid="navigate-target"');
  });
});
