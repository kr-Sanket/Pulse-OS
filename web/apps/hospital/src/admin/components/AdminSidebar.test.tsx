import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AdminSidebar, ADMIN_NAV_LINKS } from "./AdminSidebar";

const mockUser = {
  displayName: "Platform Admin",
  email: "sysadmin@pulseos.org",
};

vi.mock("@pulseos/ui", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@pulseos/ui");
  return {
    ...actual,
    useAuth: () => ({
      user: mockUser,
      signOutUser: vi.fn(),
    }),
  };
});

describe("AdminSidebar", () => {
  it("renders dedicated admin navigation items only", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminSidebar open={false} onNavigate={vi.fn()} />
      </MemoryRouter>,
    );

    // Admin items exist
    expect(html).toContain("Dashboard");
    expect(html).toContain("Hospital Verification");

    // Hospital-specific clinical/account items are NOT present
    expect(html).not.toContain("Upload a Record");
    expect(html).not.toContain("Uploaded Records");
    expect(html).not.toContain("Doctors");
    expect(html).not.toContain("My Hospital");
    expect(html).not.toContain("Audit History");
  });

  it("displays clear System Admin branding and section heading", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminSidebar open={false} onNavigate={vi.fn()} />
      </MemoryRouter>,
    );

    expect(html).toContain("PulseOS");
    expect(html).toContain("System Administrator");
    expect(html).toContain("Platform Administration");
  });

  it("renders authenticated administrator details and logout button in footer", () => {
    const html = renderToString(
      <MemoryRouter>
        <AdminSidebar open={false} onNavigate={vi.fn()} />
      </MemoryRouter>,
    );

    expect(html).toContain("Platform Admin");
    expect(html).toContain("sysadmin@pulseos.org");
    expect(html).toContain("Sign out");
  });

  it("declares exact navigable targets for administrative routes", () => {
    expect(ADMIN_NAV_LINKS.map((item) => item.to)).toEqual(["/admin", "/admin/verification"]);
  });
});
