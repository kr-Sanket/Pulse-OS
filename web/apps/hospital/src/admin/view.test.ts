import { describe, expect, it } from "vitest";

import type { Hospital } from "./api";
import { formatVerifierId, toReviewItemFromResponse, validateHospitalId } from "./view";

describe("admin/view", () => {
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
