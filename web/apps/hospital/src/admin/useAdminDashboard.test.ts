import { describe, expect, it } from "vitest";

import { computeAdminMetrics } from "./useAdminDashboard";
import type { HospitalReviewItem } from "./view";

describe("computeAdminMetrics", () => {
  it("accurately calculates counts for mixed pending and verified hospitals", () => {
    const hospitals: readonly HospitalReviewItem[] = [
      { hid: "HID-0001", name: "Metro General", address: "123 Main St", status: "VERIFIED" },
      { hid: "HID-0002", name: "City Care", address: "456 Oak St", status: "PENDING" },
      { hid: "HID-0003", name: "Valley Health", address: "789 Pine St", status: "VERIFIED" },
      { hid: "HID-0004", name: "St. Jude Clinic", address: null, status: "PENDING" },
    ];

    const metrics = computeAdminMetrics(hospitals);

    expect(metrics).toEqual({
      totalCount: 4,
      pendingCount: 2,
      verifiedCount: 2,
    });
  });

  it("returns zero counts for an empty hospital directory", () => {
    const metrics = computeAdminMetrics([]);

    expect(metrics).toEqual({
      totalCount: 0,
      pendingCount: 0,
      verifiedCount: 0,
    });
  });

  it("returns 0 pending when all registered hospitals are verified", () => {
    const hospitals: readonly HospitalReviewItem[] = [
      { hid: "HID-0001", name: "Metro General", address: null, status: "VERIFIED" },
      { hid: "HID-0002", name: "City Care", address: null, status: "VERIFIED" },
    ];

    const metrics = computeAdminMetrics(hospitals);

    expect(metrics.totalCount).toBe(2);
    expect(metrics.pendingCount).toBe(0);
    expect(metrics.verifiedCount).toBe(2);
  });
});
