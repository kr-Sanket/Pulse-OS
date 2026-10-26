import { describe, expect, it } from "vitest";
import type { Hospital } from "./api";
import {
  FILTER_OPTIONS,
  formatVerifierId,
  historyPanelState,
  LIFECYCLE_ACTION_CONFIG,
  toReviewItemFromResponse,
  validateHospitalId,
  VERIFICATION_STATUS_CONFIG,
} from "./view";

describe("admin/view", () => {
  describe("historyPanelState", () => {
    it("shows loading until the first page arrives", () => {
      expect(historyPanelState(true, null, null)).toBe("loading");
      expect(historyPanelState(false, null, null)).toBe("loading");
    });

    it("never presents a failed load as an empty history", () => {
      expect(historyPanelState(false, "Access denied.", null)).toBe("error");
      expect(historyPanelState(false, "Access denied.", [])).toBe("error");
    });

    it("distinguishes an empty trail from a populated one", () => {
      expect(historyPanelState(false, null, [])).toBe("empty");
      expect(historyPanelState(false, null, [{ id: "e1" }])).toBe("list");
    });

    it("shows loading while a reload replaces cached entries", () => {
      expect(historyPanelState(true, null, [{ id: "e1" }])).toBe("loading");
    });
  });

  describe("VERIFICATION_STATUS_CONFIG and LIFECYCLE_ACTION_CONFIG", () => {
    it("configures all four verification statuses", () => {
      expect(VERIFICATION_STATUS_CONFIG.PENDING.label).toBe("Pending Verification");
      expect(VERIFICATION_STATUS_CONFIG.VERIFIED.label).toBe("Verified");
      expect(VERIFICATION_STATUS_CONFIG.REJECTED.label).toBe("Rejected");
      expect(VERIFICATION_STATUS_CONFIG.SUSPENDED.label).toBe("Suspended");
    });

    it("configures all four lifecycle actions", () => {
      expect(LIFECYCLE_ACTION_CONFIG.VERIFIED.label).toBe("Verified");
      expect(LIFECYCLE_ACTION_CONFIG.REJECTED.label).toBe("Rejected");
      expect(LIFECYCLE_ACTION_CONFIG.SUSPENDED.label).toBe("Suspended");
      expect(LIFECYCLE_ACTION_CONFIG.REINSTATED.label).toBe("Reinstated");
    });

    it("includes all 5 filter options", () => {
      const ids = FILTER_OPTIONS.map((f) => f.id);
      expect(ids).toEqual(["ALL", "PENDING", "VERIFIED", "SUSPENDED", "REJECTED"]);
    });
  });

  describe("formatVerifierId", () => {
    it("returns shortened 8-char identifier for a UUID", () => {
      expect(formatVerifierId("123e4567-e89b-12d3-a456-426614174000")).toBe("123e4567");
    });

    it("returns null for null, undefined, or empty string", () => {
      expect(formatVerifierId(null)).toBeNull();
      expect(formatVerifierId(undefined)).toBeNull();
      expect(formatVerifierId("")).toBeNull();
    });
  });

  describe("toReviewItemFromResponse", () => {
    it("maps verified hospital response including attribution fields", () => {
      const response: Hospital = {
        hid: "HID-1234",
        name: "Test Hospital",
        address: "123 Medical Way",
        verificationStatus: "VERIFIED",
        createdAt: "2026-10-17T10:00:00Z",
        verifiedAt: "2026-10-17T12:00:00Z",
        verifiedByUserId: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      };

      const item = toReviewItemFromResponse(response);
      expect(item.hid).toBe("HID-1234");
      expect(item.name).toBe("Test Hospital");
      expect(item.address).toBe("123 Medical Way");
      expect(item.status).toBe("VERIFIED");
      expect(item.verifiedAt).toBe("2026-10-17T12:00:00Z");
      expect(item.verifiedByUserId).toBe("a1b2c3d4-e5f6-7890-abcd-ef1234567890");
    });

    it("maps rejected and suspended hospitals", () => {
      const rej: Hospital = {
        hid: "HID-1111",
        name: "Rejected Clinic",
        address: null,
        verificationStatus: "REJECTED",
        createdAt: "2026-10-01T00:00:00Z",
      };
      expect(toReviewItemFromResponse(rej).status).toBe("REJECTED");

      const susp: Hospital = {
        hid: "HID-2222",
        name: "Suspended Clinic",
        address: null,
        verificationStatus: "SUSPENDED",
        createdAt: "2026-10-01T00:00:00Z",
      };
      expect(toReviewItemFromResponse(susp).status).toBe("SUSPENDED");
    });

    it("maps legacy verified hospital without attribution fields gracefully", () => {
      const legacyResponse: Hospital = {
        hid: "HID-5678",
        name: "Legacy Hospital",
        address: null,
        verificationStatus: "VERIFIED",
        createdAt: "2026-01-01T00:00:00Z",
        verifiedAt: null,
        verifiedByUserId: null,
      };

      const item = toReviewItemFromResponse(legacyResponse);
      expect(item.hid).toBe("HID-5678");
      expect(item.status).toBe("VERIFIED");
      expect(item.verifiedAt).toBeNull();
      expect(item.verifiedByUserId).toBeNull();
    });
  });

  describe("validateHospitalId", () => {
    it("accepts valid HID formats", () => {
      expect(validateHospitalId("HID-0001")).toBeNull();
      expect(validateHospitalId("  hid-abcd  ")).toBeNull();
    });

    it("rejects empty or invalid HID formats", () => {
      expect(validateHospitalId("")).toBe("Hospital ID (HID) is required.");
      expect(validateHospitalId("INVALID")).toContain("must match the format 'HID-XXXX'");
    });
  });
});
