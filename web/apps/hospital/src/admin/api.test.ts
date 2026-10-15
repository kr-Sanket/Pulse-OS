import { describe, expect, it, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import {
  fetchCurrentUser,
  listHospitals,
  verifyHospital,
  type AuthenticatedUser,
  type Hospital,
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
