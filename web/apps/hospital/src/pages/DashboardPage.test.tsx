import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HospitalAdminProfile } from "@/profile/api";
import { DashboardPage } from "./DashboardPage";

interface ProfileState {
  status: "idle" | "loading" | "ready" | "error";
  data?: { kind: "registered"; profile: HospitalAdminProfile } | { kind: "unregistered" };
  message?: string;
}

import type { CurrentUserRoleState } from "@/components/layout/useCurrentUserRole";

let mockProfileResource: ProfileState = { status: "ready", data: { kind: "unregistered" } };
let mockRoleState: CurrentUserRoleState = { role: "HOSPITAL_ADMIN", loading: false, error: null };

vi.mock("@/components/layout/useCurrentUserRole", () => ({
  useCurrentUserRole: () => mockRoleState,
}));

vi.mock("@/profile/useHospitalProfile", () => ({
  useHospitalProfile: () => ({
    resource: mockProfileResource,
    reload: vi.fn(),
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("react-router-dom");
  return {
    ...actual,
    Navigate: ({ to }: { to: string }) => <div data-testid="navigate" data-to={to} />,
  };
});

describe("DashboardPage", () => {
  beforeEach(() => {
    mockProfileResource = { status: "ready", data: { kind: "unregistered" } };
    mockRoleState = { role: "HOSPITAL_ADMIN", loading: false, error: null };
  });

  it("redirects unregistered user to /register", () => {
    mockProfileResource = { status: "ready", data: { kind: "unregistered" } };

    const html = renderToString(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate"');
    expect(html).toContain('data-to="/register"');
  });

  it("redirects PENDING hospital to /register (waiting screen)", () => {
    mockProfileResource = {
      status: "ready",
      data: {
        kind: "registered",
        profile: {
          adminFullName: "Dr. Test Admin",
          hospital: {
            hid: "HID-0004",
            name: "Metro General Hospital",
            address: "42 Healthcare Way",
            verificationStatus: "PENDING",
            createdAt: "2026-10-15T00:00:00Z",
          },
        },
      },
    };

    const html = renderToString(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate"');
    expect(html).toContain('data-to="/register"');
  });

  it("renders dashboard when hospital is VERIFIED", () => {
    mockProfileResource = {
      status: "ready",
      data: {
        kind: "registered",
        profile: {
          adminFullName: "Dr. Test Admin",
          hospital: {
            hid: "HID-0004",
            name: "Metro General Hospital",
            address: "42 Healthcare Way",
            verificationStatus: "VERIFIED",
            createdAt: "2026-10-15T00:00:00Z",
          },
        },
      },
    };

    const html = renderToString(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Metro General Hospital");
    expect(html).toContain("HID-0004");
    expect(html).toContain("What you can do here");
    expect(html).toContain("Your hospital is verified");
    expect(html).not.toContain('data-testid="navigate"');
  });

  it("redirects SYSTEM_ADMIN to /admin", () => {
    const html = renderToString(
      <MemoryRouter>
        <DashboardPage
          useRole={() => ({
            role: "SYSTEM_ADMIN",
            loading: false,
            error: null,
          })}
        />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate"');
    expect(html).toContain('data-to="/admin"');
  });

  it("renders skeleton while role is loading", () => {
    mockRoleState = { role: null, loading: true, error: null };

    const html = renderToString(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-slot="skeleton"');
    expect(html).not.toContain('data-testid="navigate"');
  });

  it("renders error state when profile fails with error", () => {
    mockProfileResource = { status: "error", message: "Failed to connect to PulseOS API." };

    const html = renderToString(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Could not load your hospital.");
    expect(html).toContain("Failed to connect to PulseOS API.");
  });
});
