import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AdminDashboardPage } from "./AdminDashboardPage";
import type { AdminDashboardState } from "@/admin/useAdminDashboard";

describe("AdminDashboardPage", () => {
  it("renders metric counts derived from backend records and queue action", () => {
    const mockState: AdminDashboardState = {
      loading: false,
      error: null,
      metrics: {
        totalCount: 3,
        pendingCount: 1,
        verifiedCount: 2,
      },
      pendingHospitals: [
        {
          hid: "HID-0003",
          name: "Apollo Hospital",
          address: "Chennai, TN",
          status: "PENDING",
        },
      ],
      allHospitals: [
        {
          hid: "HID-0001",
          name: "Tata Main Hospital",
          address: "Jamshedpur, JH",
          status: "VERIFIED",
        },
        {
          hid: "HID-0002",
          name: "CMC Vellore",
          address: "Vellore, TN",
          status: "VERIFIED",
        },
        {
          hid: "HID-0003",
          name: "Apollo Hospital",
          address: "Chennai, TN",
          status: "PENDING",
        },
      ],
      refresh: vi.fn(),
    };

    const html = renderToString(
      <MemoryRouter>
        <AdminDashboardPage state={mockState} />
      </MemoryRouter>,
    );

    // Metric numbers
    expect(html).toContain("Pending Verification");
    expect(html).toContain("1 hospital awaiting review");
    expect(html).toContain("Verified Hospitals");
    expect(html).toContain("Total Registered");

    // Action button / links to verification queue
    expect(html).toContain("Open Verification Queue");
    expect(html).toContain("/admin/verification");

    // Pending review section
    expect(html).toContain("Awaiting Administrative Review");
    expect(html).toContain("Apollo Hospital");
    expect(html).toContain("HID-0003");

    // All registered directory
    expect(html).toContain("Registered Organizations Directory");
    expect(html).toContain("Tata Main Hospital");
    expect(html).toContain("CMC Vellore");
  });

  it("renders clear-queue message when there are zero pending hospitals", () => {
    const mockState: AdminDashboardState = {
      loading: false,
      error: null,
      metrics: {
        totalCount: 2,
        pendingCount: 0,
        verifiedCount: 2,
      },
      pendingHospitals: [],
      allHospitals: [
        {
          hid: "HID-0001",
          name: "TMH",
          address: null,
          status: "VERIFIED",
        },
      ],
      refresh: vi.fn(),
    };

    const html = renderToString(
      <MemoryRouter>
        <AdminDashboardPage state={mockState} />
      </MemoryRouter>,
    );

    expect(html).toContain("0");
    expect(html).toContain("All registered hospital organizations are currently verified");
    expect(html).not.toContain("Awaiting Administrative Review");
  });

  it("renders empty state when no hospitals exist in the platform", () => {
    const mockState: AdminDashboardState = {
      loading: false,
      error: null,
      metrics: {
        totalCount: 0,
        pendingCount: 0,
        verifiedCount: 0,
      },
      pendingHospitals: [],
      allHospitals: [],
      refresh: vi.fn(),
    };

    const html = renderToString(
      <MemoryRouter>
        <AdminDashboardPage state={mockState} />
      </MemoryRouter>,
    );

    expect(html).toContain("No hospitals registered yet");
  });

  it("renders error state with retry action when loading fails", () => {
    const mockState: AdminDashboardState = {
      loading: false,
      error: "Access denied. Only PulseOS System Administrators are authorized.",
      metrics: { totalCount: 0, pendingCount: 0, verifiedCount: 0 },
      pendingHospitals: [],
      allHospitals: [],
      refresh: vi.fn(),
    };

    const html = renderToString(
      <MemoryRouter>
        <AdminDashboardPage state={mockState} />
      </MemoryRouter>,
    );

    expect(html).toContain("Could not load platform metrics.");
    expect(html).toContain("Access denied");
    expect(html).toContain("Try Again");
  });

  it("renders verification attribution for verified hospital and handles legacy record without attribution", () => {
    const mockState: AdminDashboardState = {
      loading: false,
      error: null,
      metrics: { totalCount: 2, pendingCount: 0, verifiedCount: 2 },
      pendingHospitals: [],
      allHospitals: [
        {
          hid: "HID-0001",
          name: "Tata Main Hospital",
          address: "Jamshedpur, JH",
          status: "VERIFIED",
          verifiedAt: "2026-10-17T14:30:00Z",
          verifiedByUserId: "11112222-3333-4444-5555-666677778888",
        },
        {
          hid: "HID-0002",
          name: "Legacy Hospital",
          address: "Vellore, TN",
          status: "VERIFIED",
          verifiedAt: null,
          verifiedByUserId: null,
        },
      ],
      refresh: vi.fn(),
    };

    const html = renderToString(
      <MemoryRouter>
        <AdminDashboardPage state={mockState} />
      </MemoryRouter>,
    );

    expect(html).toContain("Tata Main Hospital");
    expect(html).toContain("Admin (11112222)");
    expect(html).toContain("Legacy Hospital");
  });
});
