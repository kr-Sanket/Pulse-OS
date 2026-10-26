import { describe, expect, it, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import {
  fetchCurrentUser,
  fetchHospitalAuditLogs,
  listHospitals,
  reinstateHospital,
  rejectHospital,
  suspendHospital,
  verifyHospital,
  type AuthenticatedUser,
  type Hospital,
  type HospitalAuditLogList,
} from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function ok(data: unknown, status = 200): StubResult {
  return { data, response: { status } };
}

function fail(status: number, error?: unknown): StubResult {
  return { error: error ?? {}, response: { status } };
}

function stubClient(results: StubResult[]) {
  const POST = vi.fn(() => {
    const next = results.shift();
    if (!next) throw new Error("Unexpected POST call");
    return Promise.resolve(next);
  });
  const GET = vi.fn(() => {
    const next = results.shift();
    if (!next) throw new Error("Unexpected GET call");
    return Promise.resolve(next);
  });
  return {
    client: { POST, GET } as unknown as PulseOSClient,
    POST,
    GET,
  };
}

describe("System Admin API: verifyHospital", () => {
  it("successfully verifies hospital and returns verified HospitalResponse", async () => {
    const verifiedResponse: Hospital = {
      hid: "HID-0001",
      name: "TMH Jamshedpur",
      address: "Jamshedpur, Jharkhand",
      createdAt: "2026-01-01T00:00:00Z",
      verificationStatus: "VERIFIED",
    };

    const { client, POST } = stubClient([ok(verifiedResponse)]);

    const result = await verifyHospital(client, "HID-0001");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.verificationStatus).toBe("VERIFIED");
      expect(result.data.name).toBe("TMH Jamshedpur");
      expect(result.data.hid).toBe("HID-0001");
    }

    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/verify", {
      params: { path: { hid: "HID-0001" } },
    });
  });

  it("normalizes HID to uppercase and trimmed", async () => {
    const verifiedResponse: Hospital = {
      hid: "HID-0002",
      name: "CMC Vellore",
      address: null,
      createdAt: "2026-01-01T00:00:00Z",
      verificationStatus: "VERIFIED",
    };

    const { client, POST } = stubClient([ok(verifiedResponse)]);

    const result = await verifyHospital(client, "  hid-0002  ");
    expect(result.status).toBe("ready");
    expect(POST).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/verify", {
      params: { path: { hid: "HID-0002" } },
    });
  });

  it("handles 403 Forbidden with clear access denied message", async () => {
    const { client } = stubClient([fail(403, { detail: "Insufficient role for this operation." })]);

    const result = await verifyHospital(client, "HID-0001");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("Insufficient role");
    }
  });

  it("handles 404 Hospital Not Found clearly", async () => {
    const { client } = stubClient([fail(404, { detail: "Hospital not found." })]);

    const result = await verifyHospital(client, "HID-9999");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("Hospital not found");
    }
  });

  it("handles 401 Session Expired clearly", async () => {
    const { client } = stubClient([fail(401)]);

    const result = await verifyHospital(client, "HID-0001");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("session has expired");
    }
  });
});

describe("System Admin API: fetchCurrentUser", () => {
  it("successfully returns current authenticated user and role", async () => {
    const userResponse: AuthenticatedUser = {
      userId: "user-1",
      firebaseUid: "fb-sys",
      role: "SYSTEM_ADMIN",
    };

    const { client, GET } = stubClient([ok(userResponse)]);

    const result = await fetchCurrentUser(client);
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.role).toBe("SYSTEM_ADMIN");
      expect(result.data.userId).toBe("user-1");
    }
    expect(GET).toHaveBeenCalledWith("/api/v1/auth/me", { signal: undefined });
  });

  it("handles auth error response", async () => {
    const { client } = stubClient([fail(401)]);

    const result = await fetchCurrentUser(client);
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("session has expired");
    }
  });
});

describe("System Admin API: listHospitals", () => {
  it("successfully fetches hospital list without status filter", async () => {
    const mockList = {
      items: [
        {
          hid: "HID-0001",
          name: "Hospital Alpha",
          address: "123 Street",
          createdAt: "2026-01-01T00:00:00Z",
          verificationStatus: "PENDING" as const,
        },
      ],
    };

    const { client, GET } = stubClient([ok(mockList)]);

    const result = await listHospitals(client);
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.items).toHaveLength(1);
      expect(result.data.items[0]?.hid).toBe("HID-0001");
    }
    expect(GET).toHaveBeenCalledWith("/api/v1/hospitals", {
      params: { query: undefined },
      signal: undefined,
    });
  });

  it("passes status filter query param when provided", async () => {
    const mockList = {
      items: [
        {
          hid: "HID-0002",
          name: "Hospital Beta",
          address: null,
          createdAt: "2026-01-01T00:00:00Z",
          verificationStatus: "VERIFIED" as const,
        },
      ],
    };

    const { client, GET } = stubClient([ok(mockList)]);

    const result = await listHospitals(client, { status: "VERIFIED" });
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.items[0]?.verificationStatus).toBe("VERIFIED");
    }
    expect(GET).toHaveBeenCalledWith("/api/v1/hospitals", {
      params: { query: { status: "VERIFIED" } },
      signal: undefined,
    });
  });

  it("handles 403 Forbidden with clear access denied message", async () => {
    const { client } = stubClient([fail(403, { detail: "Access denied." })]);

    const result = await listHospitals(client);
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("Access denied");
    }
  });

  it("handles 401 Session Expired", async () => {
    const { client } = stubClient([fail(401)]);

    const result = await listHospitals(client);
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("session has expired");
    }
  });
});

describe("System Admin API: rejectHospital", () => {
  it("successfully rejects hospital with reason and returns updated HospitalResponse", async () => {
    const rejectedResponse: Hospital = {
      hid: "HID-0001",
      name: "TMH Jamshedpur",
      address: "Jamshedpur, Jharkhand",
      createdAt: "2026-01-01T00:00:00Z",
      verificationStatus: "REJECTED",
    };

    const { client, POST } = stubClient([ok(rejectedResponse)]);

    const result = await rejectHospital(client, "HID-0001", "Missing required license");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.verificationStatus).toBe("REJECTED");
    }

    expect(POST).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/reject", {
      params: { path: { hid: "HID-0001" } },
      body: { reason: "Missing required license" },
    });
  });

  it("handles 409 transition error clearly", async () => {
    const { client } = stubClient([
      fail(409, { detail: "Hospital status VERIFIED cannot transition to REJECTED" }),
    ]);

    const result = await rejectHospital(client, "HID-0001");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toContain("cannot transition");
    }
  });
});

describe("System Admin API: suspendHospital", () => {
  it("successfully suspends hospital with optional reason", async () => {
    const suspendedResponse: Hospital = {
      hid: "HID-0001",
      name: "TMH Jamshedpur",
      address: null,
      createdAt: "2026-01-01T00:00:00Z",
      verificationStatus: "SUSPENDED",
    };

    const { client, POST } = stubClient([ok(suspendedResponse)]);

    const result = await suspendHospital(client, "HID-0001", "Compliance audit pending");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.verificationStatus).toBe("SUSPENDED");
    }

    expect(POST).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/suspend", {
      params: { path: { hid: "HID-0001" } },
      body: { reason: "Compliance audit pending" },
    });
  });
});

describe("System Admin API: reinstateHospital", () => {
  it("successfully reinstates hospital with optional reason", async () => {
    const reinstatedResponse: Hospital = {
      hid: "HID-0001",
      name: "TMH Jamshedpur",
      address: null,
      createdAt: "2026-01-01T00:00:00Z",
      verificationStatus: "VERIFIED",
    };

    const { client, POST } = stubClient([ok(reinstatedResponse)]);

    const result = await reinstateHospital(client, "HID-0001", "Compliance audit passed");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.verificationStatus).toBe("VERIFIED");
    }

    expect(POST).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/reinstate", {
      params: { path: { hid: "HID-0001" } },
      body: { reason: "Compliance audit passed" },
    });
  });
});

describe("System Admin API: fetchHospitalAuditLogs", () => {
  it("successfully fetches lifecycle audit history", async () => {
    const auditResponse: HospitalAuditLogList = {
      items: [
        {
          id: "log-1",
          hospitalId: "h-1",
          actorUserId: "admin-1",
          action: "REINSTATED",
          reason: "Approved after review",
          occurredAt: "2026-10-26T10:00:00Z",
          createdAt: "2026-10-26T10:00:00Z",
        },
      ],
      nextCursor: null,
    };

    const { client, GET } = stubClient([ok(auditResponse)]);

    const result = await fetchHospitalAuditLogs(client, "HID-0001");
    expect(result.status).toBe("ready");
    if (result.status === "ready") {
      expect(result.data.items).toHaveLength(1);
      expect(result.data.items[0]?.action).toBe("REINSTATED");
    }

    expect(GET).toHaveBeenCalledWith("/api/v1/hospitals/{hid}/audit-logs", {
      params: { path: { hid: "HID-0001" } },
      signal: undefined,
    });
  });
});
