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
    {
      hid: "HID-0003",
      name: "Apollo Delhi",
      address: "Delhi",
      status: "SUSPENDED",
    },
    {
      hid: "HID-0004",
      name: "City Clinic",
      address: "Mumbai",
      status: "REJECTED",
    },
  ],
  filter: "ALL",
  busyHid: null,
  error: null,
  success: null,
  verify: vi.fn(),
  reject: vi.fn(),
  suspend: vi.fn(),
  reinstate: vi.fn(),
  fetchAuditLogs: vi.fn().mockResolvedValue([]),
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

  it("renders Reject button for PENDING hospital when onReject is provided", () => {
    const onVerify = vi.fn();
    const onReject = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard
        hospital={BASE_HOSPITAL}
        busy={false}
        onVerify={onVerify}
        onReject={onReject}
      />,
    );

    expect(html).toContain("Verify Hospital");
    expect(html).toContain("Reject");
  });

  it("renders Suspend action button when hospital is VERIFIED", () => {
    const onVerify = vi.fn();
    const onSuspend = vi.fn();
    const verifiedHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "VERIFIED",
    };

    const html = renderToString(
      <HospitalVerificationCard
        hospital={verifiedHospital}
        busy={false}
        onVerify={onVerify}
        onSuspend={onSuspend}
      />,
    );

    expect(html).toContain("Verified");
    expect(html).toContain("Organization can register doctors and upload records");
    expect(html).toContain("Suspend");
  });

  it("renders Reinstate action button when hospital is SUSPENDED", () => {
    const onVerify = vi.fn();
    const onReinstate = vi.fn();
    const suspendedHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "SUSPENDED",
    };

    const html = renderToString(
      <HospitalVerificationCard
        hospital={suspendedHospital}
        busy={false}
        onVerify={onVerify}
        onReinstate={onReinstate}
      />,
    );

    expect(html).toContain("Suspended");
    expect(html).toContain("Reinstate");
  });

  it("renders Terminal State badge and prevents actions when hospital is REJECTED", () => {
    const onVerify = vi.fn();
    const onReject = vi.fn();
    const onSuspend = vi.fn();
    const onReinstate = vi.fn();
    const rejectedHospital: HospitalReviewItem = {
      ...BASE_HOSPITAL,
      status: "REJECTED",
    };

    const html = renderToString(
      <HospitalVerificationCard
        hospital={rejectedHospital}
        busy={false}
        onVerify={onVerify}
        onReject={onReject}
        onSuspend={onSuspend}
        onReinstate={onReinstate}
      />,
    );

    expect(html).toContain("Rejected");
    expect(html).toContain("Terminal State");
    expect(html).not.toContain("Verify Hospital");
    expect(html).not.toContain("Reinstate");
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

  it("renders busy state and disables actions while action is in-flight", () => {
    const onVerify = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard hospital={BASE_HOSPITAL} busy={true} onVerify={onVerify} />,
    );

    expect(html).toContain("Verifying…");
    expect(html).toContain('disabled=""');
  });

  it("renders View Audit History toggle button", () => {
    const onVerify = vi.fn();
    const html = renderToString(
      <HospitalVerificationCard hospital={BASE_HOSPITAL} busy={false} onVerify={onVerify} />,
    );

    expect(html).toContain("View Audit History");
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
    expect(html).not.toContain("Hospital Account Verification");
  });

  it("renders full System Admin verification view with all 5 filter options", () => {
    const html = renderToString(<SystemAdminVerificationView state={BASE_STATE} />);

    expect(html).toContain("Hospital Account Verification");
    expect(html).toContain("System Admin");
    expect(html).toContain("Verify Directly by Hospital ID (HID)");
    expect(html).toContain("All Hospitals");
    expect(html).toContain("Pending Verification");
    expect(html).toContain("Verified");
    expect(html).toContain("Suspended");
    expect(html).toContain("Rejected");
    expect(html).toContain("TMH Jamshedpur");
    expect(html).toContain("CMC Vellore");
    expect(html).toContain("Apollo Delhi");
    expect(html).toContain("City Clinic");
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

  it("displays success banner when action succeeds", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      success: 'Hospital "TMH Jamshedpur" (HID-0001) has been successfully verified.',
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("TMH Jamshedpur");
    expect(html).toContain("has been successfully verified");
  });

  it("displays error banner when an action fails", () => {
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

  it("displays empty state for suspended filter when no hospitals are suspended", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      filter: "SUSPENDED",
      hospitals: [],
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("No suspended hospitals found");
  });

  it("displays empty state for rejected filter when no hospitals are rejected", () => {
    const state: HospitalVerificationState = {
      ...BASE_STATE,
      filter: "REJECTED",
      hospitals: [],
    };

    const html = renderToString(<SystemAdminVerificationView state={state} />);
    expect(html).toContain("No rejected hospitals found");
  });

  it("displays backend capability disclosure for ADR-015 and ADR-034", () => {
    const html = renderToString(<SystemAdminVerificationView state={BASE_STATE} />);
    expect(html).toContain("Platform Verification Architecture &amp; Backend Contract");
    expect(html).toContain("Lifecycle &amp; Audit (ADR-034)");
    expect(html).toContain("POST /api/v1/hospitals/{hid}/reject");
    expect(html).toContain("POST /api/v1/hospitals/{hid}/suspend");
    expect(html).toContain("POST /api/v1/hospitals/{hid}/reinstate");
    expect(html).toContain("GET /api/v1/hospitals/{hid}/audit-logs");
  });
});
