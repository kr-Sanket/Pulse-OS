import { describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";

import { HospitalVerificationCard } from "./components/HospitalVerificationCard";
import { SystemAdminVerificationView } from "./components/SystemAdminVerificationView";
import type { HospitalVerificationState } from "./useHospitalVerification";
import type { HospitalReviewItem } from "./view";

const BASE_HOSPITAL: HospitalReviewItem = {
  hid: "HID-0001",
  name: "TMH Jamshedpur",
  address: "Jamshedpur, Jharkhand",
  status: "PENDING",
};

const BASE_STATE: HospitalVerificationState = {
  authLoading: false,
  userRole: "SYSTEM_ADMIN",
  isAuthorized: true,
  authError: null,
  loadingHospitals: false,
  loadError: null,
  hospitals: [
    BASE_HOSPITAL,
    {
      hid: "HID-0002",
      name: "CMC Vellore",
      address: "Vellore, Tamil Nadu",
      status: "VERIFIED",
    },
  ],
  filter: "ALL",
  busyHid: null,
  error: null,
  success: null,
  verify: vi.fn(),
  refresh: vi.fn(),
  setFilter: vi.fn(),
  dismissAlerts: vi.fn(),
};

describe("HospitalVerificationCard", () => {
  it("renders hospital name, HID, address, and Pending status badge", () => {
    const onVerify = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard hospital={BASE_HOSPITAL} busy={false} onVerify={onVerify} />,
    );

    expect(html).toContain("TMH Jamshedpur");
    expect(html).toContain("HID-0001");
    expect(html).toContain("Jamshedpur, Jharkhand");
    expect(html).toContain("Pending Verification");
    expect(html).toContain("Verify Hospital");
  });

  it("renders Verified badge and disabled status when hospital is already VERIFIED", () => {
    const onVerify = vi.fn();
    const verifiedHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "VERIFIED",
    };

    const html = renderToString(
      <HospitalVerificationCard hospital={verifiedHospital} busy={false} onVerify={onVerify} />,
    );

    expect(html).toContain("Verified");
    expect(html).toContain("Organization can register doctors and upload records");
    // Verify button should be disabled for already verified hospital
    expect(html).toContain('disabled=""');
  });

  it("renders verification timestamp and shortened verifier UUID when attribution is present", () => {
    const onVerify = vi.fn();
    const attributedHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "VERIFIED",
      verifiedAt: "2026-10-17T12:00:00Z",
      verifiedByUserId: "98765432-1234-5678-90ab-cdef01234567",
    };

    const html = renderToString(
      <HospitalVerificationCard hospital={attributedHospital} busy={false} onVerify={onVerify} />,
    );

    expect(html).toContain("Verified");
    expect(html).toContain("Admin (98765432)");
  });

  it("handles missing attribution metadata gracefully for legacy VERIFIED hospitals", () => {
    const onVerify = vi.fn();
    const legacyHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "VERIFIED",
      verifiedAt: null,
      verifiedByUserId: null,
    };

    const html = renderToString(
      <HospitalVerificationCard hospital={legacyHospital} busy={false} onVerify={onVerify} />,
    );

    expect(html).toContain("Verified");
    expect(html).toContain("Organization can register doctors and upload records");
    expect(html).not.toContain("Admin (");
  });

  it("renders busy state and disables actions while verification is in-flight", () => {
    const onVerify = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard hospital={BASE_HOSPITAL} busy={true} onVerify={onVerify} />,
    );

    expect(html).toContain("Verifying…");
    expect(html).toContain('disabled=""');
  });

  it("omits rejection button because backend does not support rejection", () => {
    const onVerify = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard hospital={BASE_HOSPITAL} busy={false} onVerify={onVerify} />,
    );

    expect(html).not.toContain("Reject Hospital");
    expect(html).not.toContain("Decline Hospital");
  });
});

describe("SystemAdminVerificationView", () => {
  it("renders loading indicator during authorization check", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      authLoading: true,
      isAuthorized: false,
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("Checking administrative permissions…");
    expect(html).toContain("Verifying your role against the PulseOS security authority");
  });

  it("renders unauthorized access alert when user role is not SYSTEM_ADMIN", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      authLoading: false,
      userRole: "HOSPITAL_ADMIN",
      isAuthorized: false,
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("System Administrator Access Required");
    expect(html).toContain("HOSPITAL_ADMIN");
    expect(html).toContain("is not authorized to review or verify hospital accounts");
    // Action inputs and buttons must not be visible to unauthorized users
    expect(html).not.toContain("Hospital Account Verification");
  });

  it("renders full System Admin verification view when user is SYSTEM_ADMIN", () => {
    const html = renderToString(<SystemAdminVerificationView state={BASE_STATE} />);

    expect(html).toContain("Hospital Account Verification");
    expect(html).toContain("System Admin");
    expect(html).toContain("Verify Directly by Hospital ID (HID)");
    expect(html).toContain("All Hospitals");
    expect(html).toContain("Pending Verification");
    expect(html).toContain("TMH Jamshedpur");
    expect(html).toContain("CMC Vellore");
  });

  it("renders loading state when fetching real server records", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      loadingHospitals: true,
      hospitals: [],
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("Loading hospital directory…");
    expect(html).toContain("Fetching live persisted records from PulseOS");
  });

  it("renders error state when fetching server records fails", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      loadError: "Network connection refused.",
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Failed to load hospitals:");
    expect(html).toContain("Network connection refused.");
    expect(html).toContain("Retry");
  });

  it("displays success banner when verification succeeds", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      success: 'Hospital "TMH Jamshedpur" (HID-0001) has been successfully verified.',
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("TMH Jamshedpur");
    expect(html).toContain("has been successfully verified");
  });

  it("displays error banner when verification fails", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      error: "Hospital not found. Check the Hospital ID (HID) and try again.",
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Hospital not found. Check the Hospital ID (HID) and try again.");
  });

  it("displays empty state for pending filter when no hospitals are pending", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      filter: "PENDING",
      hospitals: [],
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("No pending hospitals awaiting verification");
    expect(html).toContain("Refresh Directory");
  });

  it("displays empty state for verified filter when no hospitals are verified", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      filter: "VERIFIED",
      hospitals: [],
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("No verified hospitals found");
  });

  it("displays backend capability disclosure and confirms rejection omission", () => {
    const html = renderToString(<SystemAdminVerificationView state={BASE_STATE} />);
    expect(html).toContain("Platform Verification Architecture &amp; Backend Contract");
    expect(html).toContain("no rejection endpoint exists on the server");
    expect(html).toContain("Backed by <code>GET /api/v1/hospitals</code>");
  });
});
