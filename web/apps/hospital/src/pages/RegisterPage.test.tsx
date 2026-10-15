import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HospitalAdminProfile } from "@/profile/api";
import { RegisterPage } from "./RegisterPage";

interface ProfileState {
  status: "idle" | "loading" | "ready" | "error";
  data?: { kind: "registered"; profile: HospitalAdminProfile } | { kind: "unregistered" };
  message?: string;
}

let mockProfileResource: ProfileState = { status: "ready", data: { kind: "unregistered" } };
let mockRegistrationState: { kind: string; profile?: HospitalAdminProfile; message?: string } = {
  kind: "editing",
};

vi.mock("@/profile/useHospitalProfile", () => ({
  useHospitalProfile: () => ({
    resource: mockProfileResource,
    reload: vi.fn(),
  }),
}));

vi.mock("@/register/useHospitalRegistration", () => ({
  useHospitalRegistration: () => ({
    draft: { hospitalName: "", hospitalAddress: "", adminFullName: "" },
    setField: vi.fn(),
    problems: {},
    sendable: false,
    state: mockRegistrationState,
    submit: vi.fn(),
  }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("react-router-dom");
  return {
    ...actual,
    Navigate: ({ to }: { to: string }) => <div data-testid="navigate" data-to={to} />,
  };
});

describe("RegisterPage", () => {
  beforeEach(() => {
    mockProfileResource = { status: "ready", data: { kind: "unregistered" } };
    mockRegistrationState = { kind: "editing" };
  });

  it("renders registration form when user is unregistered", () => {
    const html = renderToString(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Register your hospital");
    expect(html).toContain("Hospital name");
    expect(html).toContain("Your full name");
  });

  it("renders waiting-for-verification panel when hospital is registered and PENDING", () => {
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
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Hospital registered");
    expect(html).toContain("Metro General Hospital");
    expect(html).toContain("HID-0004");
    expect(html).toContain("waiting for verification");
    expect(html).not.toContain('data-testid="navigate"');
  });

  it("redirects to dashboard when hospital is registered and VERIFIED", () => {
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
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(html).toContain('data-testid="navigate"');
    expect(html).toContain('data-to="/"');
  });

  it("renders loading screen when checking hospital profile", () => {
    mockProfileResource = { status: "loading" };

    const html = renderToString(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Checking your hospital…");
  });

  it("renders error state when profile fails with error", () => {
    mockProfileResource = { status: "error", message: "Network connection lost." };

    const html = renderToString(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );

    expect(html).toContain("Could not check your hospital.");
    expect(html).toContain("Network connection lost.");
  });
});
