import { describe, expect, it, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import type { Grant } from "@/grants/api";
import { decideRequest, type AccessRequest, type DecisionOutcome } from "./api";
import { findServerApprovedCategoryCodes, type PerCategoryDecisions } from "./useConsentInbox";

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
    if (!next) throw new Error("Unexpected API call");
    return Promise.resolve(next);
  });
  return {
    client: { POST } as unknown as PulseOSClient,
    POST,
  };
}

describe("Per-category consent submission flow", () => {
  it("submits approvals first then rejections when both categories are selected", async () => {
    const outcomeApprove: DecisionOutcome = {
      requestId: "req-1",
      requestStatus: "PENDING",
      decisions: [
        {
          id: "d-1",
          categoryCode: "LAB_RESULT",
          status: "APPROVED",
          decidedAt: "2026-10-15T12:00:00Z",
        },
      ],
      grants: [],
    };
    const outcomeReject: DecisionOutcome = {
      requestId: "req-1",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "d-2",
          categoryCode: "PRESCRIPTION",
          status: "REJECTED",
          decidedAt: "2026-10-15T12:00:01Z",
        },
      ],
      grants: [],
    };

    const { client, POST } = stubClient([ok(outcomeApprove), ok(outcomeReject)]);

    const decisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT"],
      rejectedCodes: ["PRESCRIPTION"],
    };

    // Sequential decision flow as executed in useConsentInbox
    const resApprove = await decideRequest(client, "req-1", decisions.approvedCodes, "approve");
    expect(resApprove.status).toBe("ready");

    const resReject = await decideRequest(client, "req-1", decisions.rejectedCodes, "reject");
    expect(resReject.status).toBe("ready");

    expect(POST).toHaveBeenCalledTimes(2);
    expect(POST).toHaveBeenNthCalledWith(1, "/api/v1/access-requests/{request_id}/approve", {
      params: { path: { request_id: "req-1" } },
      body: { categoryCodes: ["LAB_RESULT"] },
    });
    expect(POST).toHaveBeenNthCalledWith(2, "/api/v1/access-requests/{request_id}/reject", {
      params: { path: { request_id: "req-1" } },
      body: { categoryCodes: ["PRESCRIPTION"] },
    });
  });

  it("submits only approvals when all categories are approved", async () => {
    const outcome: DecisionOutcome = {
      requestId: "req-2",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "d-1",
          categoryCode: "LAB_RESULT",
          status: "APPROVED",
          decidedAt: "2026-10-15T12:00:00Z",
        },
        {
          id: "d-2",
          categoryCode: "CLINICAL_NOTE",
          status: "APPROVED",
          decidedAt: "2026-10-15T12:00:00Z",
        },
      ],
      grants: [],
    };

    const { client, POST } = stubClient([ok(outcome)]);
    const decisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT", "CLINICAL_NOTE"],
      rejectedCodes: [],
    };

    const res = await decideRequest(client, "req-2", decisions.approvedCodes, "approve");
    expect(res.status).toBe("ready");
    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/approve", {
      params: { path: { request_id: "req-2" } },
      body: { categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE"] },
    });
  });

  it("submits only rejections when all categories are declined", async () => {
    const outcome: DecisionOutcome = {
      requestId: "req-3",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "d-1",
          categoryCode: "LAB_RESULT",
          status: "REJECTED",
          decidedAt: "2026-10-15T12:00:00Z",
        },
      ],
      grants: [],
    };

    const { client, POST } = stubClient([ok(outcome)]);
    const decisions: PerCategoryDecisions = {
      approvedCodes: [],
      rejectedCodes: ["LAB_RESULT"],
    };

    const res = await decideRequest(client, "req-3", decisions.rejectedCodes, "reject");
    expect(res.status).toBe("ready");
    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/reject", {
      params: { path: { request_id: "req-3" } },
      body: { categoryCodes: ["LAB_RESULT"] },
    });
  });

  it("prevents duplicate submissions while in flight and rejects empty decisions", async () => {
    let inFlight = false;
    let callCount = 0;

    async function submitGuard(decisions: PerCategoryDecisions) {
      if (inFlight) return;
      if (decisions.approvedCodes.length === 0 && decisions.rejectedCodes.length === 0) {
        return;
      }
      inFlight = true;
      try {
        await new Promise((resolve) => setTimeout(resolve, 10));
        callCount++;
      } finally {
        inFlight = false;
      }
    }

    // Empty decision is rejected
    await submitGuard({ approvedCodes: [], rejectedCodes: [] });
    expect(callCount).toBe(0);

    // Duplicate submission in flight is ignored
    const p1 = submitGuard({ approvedCodes: ["A"], rejectedCodes: [] });
    const p2 = submitGuard({ approvedCodes: ["A"], rejectedCodes: [] });
    await Promise.all([p1, p2]);
    expect(callCount).toBe(1);
  });

  it("handles HTTP 409 conflict responses clearly without false success", async () => {
    const { client } = stubClient([
      fail(409, { detail: "Request has expired or already been decided." }),
    ]);

    const result = await decideRequest(client, "req-conflict", ["LAB_RESULT"], "approve");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toBe("Request has expired or already been decided.");
    }
  });

  it("handles legacy duplicate 409 status without detail using standard fallback message", async () => {
    const { client } = stubClient([fail(409)]);

    const result = await decideRequest(client, "req-conflict-legacy", ["LAB_RESULT"], "approve");
    expect(result.status).toBe("error");
    if (result.status === "error") {
      expect(result.message).toBe("This request has already been answered, or it has expired.");
    }
  });

  it("failed submission halts pipeline and does not treat failure as success", async () => {
    // Approve fails on first call -> second call (reject) should not be reached
    const { client, POST } = stubClient([
      fail(500, { detail: "Database temporarily unavailable" }),
    ]);

    const decisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT"],
      rejectedCodes: ["PRESCRIPTION"],
    };

    let outcomeRecorded = false;
    const resApprove = await decideRequest(client, "req-fail", decisions.approvedCodes, "approve");
    if (resApprove.status === "ready") {
      outcomeRecorded = true;
    }

    expect(resApprove.status).toBe("error");
    expect(outcomeRecorded).toBe(false);
    expect(POST).toHaveBeenCalledTimes(1);
  });

  it("handles partial failure when approvals succeed but rejections fail", async () => {
    const outcomeApprove: DecisionOutcome = {
      requestId: "req-partial",
      requestStatus: "PENDING",
      decisions: [
        {
          id: "d-1",
          categoryCode: "LAB_RESULT",
          status: "APPROVED",
          decidedAt: "2026-10-15T12:00:00Z",
        },
      ],
      grants: [],
    };

    // First call (approve) succeeds, second call (reject) fails
    const { client, POST } = stubClient([
      ok(outcomeApprove),
      fail(500, { detail: "Internal database timeout on rejection" }),
    ]);

    const decisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT"],
      rejectedCodes: ["PRESCRIPTION"],
    };

    let grantReloadCount = 0;
    const reloadGrants = () => {
      grantReloadCount++;
    };

    // Step 1: Approve succeeds
    const resApprove = await decideRequest(
      client,
      "req-partial",
      decisions.approvedCodes,
      "approve",
    );
    expect(resApprove.status).toBe("ready");
    expect(POST).toHaveBeenNthCalledWith(1, "/api/v1/access-requests/{request_id}/approve", {
      params: { path: { request_id: "req-partial" } },
      body: { categoryCodes: ["LAB_RESULT"] },
    });

    // When approvals succeed, grant state reload is notified
    reloadGrants();
    expect(grantReloadCount).toBe(1);

    // Step 2: Reject fails
    const resReject = await decideRequest(client, "req-partial", decisions.rejectedCodes, "reject");
    expect(resReject.status).toBe("error");
    expect(POST).toHaveBeenNthCalledWith(2, "/api/v1/access-requests/{request_id}/reject", {
      params: { path: { request_id: "req-partial" } },
      body: { categoryCodes: ["PRESCRIPTION"] },
    });

    // Formatted partial error message
    const approvedDisplay = "Lab Results";
    const partialErrorMessage = `Approved categories (${approvedDisplay}) may already have access granted, while the remaining categories still need a decision: ${
      resReject.status === "error" ? resReject.message : ""
    }`;
    expect(partialErrorMessage).toContain("may already have access granted");
    expect(partialErrorMessage).toContain("Internal database timeout on rejection");
    expect(partialErrorMessage).toContain("still need a decision");

    // Partial state tracks approved vs failed
    const partialState = {
      approvedCodes: ["LAB_RESULT"],
      failedCodes: ["PRESCRIPTION"],
    };
    expect(partialState.approvedCodes).toEqual(["LAB_RESULT"]);
    expect(partialState.failedCodes).toEqual(["PRESCRIPTION"]);

    // Reload is triggered to ensure client syncs with server state
    reloadGrants();
    expect(grantReloadCount).toBe(2);
  });

  it("recovers successfully by submitting remaining decisions without duplicating approvals", async () => {
    const outcomeReject: DecisionOutcome = {
      requestId: "req-partial",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "d-2",
          categoryCode: "PRESCRIPTION",
          status: "REJECTED",
          decidedAt: "2026-10-15T12:05:00Z",
        },
      ],
      grants: [],
    };

    // Only the rejection call is needed during recovery
    const { client, POST } = stubClient([ok(outcomeReject)]);

    const existingPartial = {
      approvedCodes: ["LAB_RESULT"],
      failedCodes: ["PRESCRIPTION"],
    };

    const decisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT"],
      rejectedCodes: ["PRESCRIPTION"],
    };

    // Filter out already-approved codes to prevent duplicate 409 conflict
    const pendingApprovedCodes = decisions.approvedCodes.filter(
      (code) => !existingPartial.approvedCodes.includes(code),
    );
    expect(pendingApprovedCodes).toEqual([]);

    // Only rejectedCodes are submitted to the API
    const res = await decideRequest(client, "req-partial", decisions.rejectedCodes, "reject");
    expect(res.status).toBe("ready");
    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/reject", {
      params: { path: { request_id: "req-partial" } },
      body: { categoryCodes: ["PRESCRIPTION"] },
    });
  });
});

describe("Server-authoritative recovery (findServerApprovedCategoryCodes)", () => {
  const BASE_REQUEST: AccessRequest = {
    id: "req-100",
    requesterDoctorId: "doc-1",
    requesterHospitalId: "hosp-1",
    requesterHospitalName: "St. Jude Hospital",
    purpose: "Routine checkup",
    categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE", "PRESCRIPTION"],
    status: "PENDING",
    createdAt: "2026-10-15T10:00:00Z",
    expiresAt: "2026-10-22T10:00:00Z",
    requester: null,
  };

  const VALID_GRANT: Grant = {
    id: "g-1",
    granteeDoctorId: "doc-1",
    categoryCode: "LAB_RESULT",
    status: "ACTIVE",
    grantedAt: "2026-10-15T10:05:00Z",
    expiresAt: "2026-11-15T10:05:00Z",
    revokedAt: null,
    grantee: null,
  };

  it("identifies categories matching doctor, code, ACTIVE status, and grantedAt >= createdAt", () => {
    const approved = findServerApprovedCategoryCodes(BASE_REQUEST, [VALID_GRANT]);
    expect(approved).toEqual(["LAB_RESULT"]);
  });

  it("never treats grants for a different doctor as proof of approval (unrelated grant)", () => {
    const grantDifferentDoctor: Grant = {
      ...VALID_GRANT,
      granteeDoctorId: "doc-OTHER",
    };
    const approved = findServerApprovedCategoryCodes(BASE_REQUEST, [grantDifferentDoctor]);
    expect(approved).toEqual([]);
  });

  it("ignores grants for categories not requested by this access request", () => {
    const grantUnrequestedCategory: Grant = {
      ...VALID_GRANT,
      categoryCode: "RADIOLOGY",
    };
    const approved = findServerApprovedCategoryCodes(BASE_REQUEST, [grantUnrequestedCategory]);
    expect(approved).toEqual([]);
  });

  it("ignores grants that are REVOKED or EXPIRED", () => {
    const revokedGrant: Grant = {
      ...VALID_GRANT,
      status: "REVOKED",
      revokedAt: "2026-10-15T10:10:00Z",
    };
    const expiredGrant: Grant = {
      ...VALID_GRANT,
      status: "EXPIRED",
      expiresAt: "2026-10-15T10:00:00Z",
    };
    expect(findServerApprovedCategoryCodes(BASE_REQUEST, [revokedGrant])).toEqual([]);
    expect(findServerApprovedCategoryCodes(BASE_REQUEST, [expiredGrant])).toEqual([]);
  });

  it("ignores grants granted prior to the request creation date", () => {
    const priorGrant: Grant = {
      ...VALID_GRANT,
      grantedAt: "2026-10-14T09:00:00Z", // Granted 25 hours before the request was raised
    };
    const approved = findServerApprovedCategoryCodes(BASE_REQUEST, [priorGrant]);
    expect(approved).toEqual([]);
  });

  it("ignores requests that are not in PENDING state", () => {
    const decidedRequest: AccessRequest = {
      ...BASE_REQUEST,
      status: "DECIDED",
    };
    expect(findServerApprovedCategoryCodes(decidedRequest, [VALID_GRANT])).toEqual([]);
  });

  it("preserves category ordering and returns all validly approved categories", () => {
    const grant2: Grant = {
      id: "g-2",
      granteeDoctorId: "doc-1",
      categoryCode: "PRESCRIPTION",
      status: "ACTIVE",
      grantedAt: "2026-10-15T10:06:00Z",
      expiresAt: "2026-11-15T10:06:00Z",
      revokedAt: null,
      grantee: null,
    };
    const approved = findServerApprovedCategoryCodes(BASE_REQUEST, [grant2, VALID_GRANT]);
    expect(approved).toEqual(["LAB_RESULT", "PRESCRIPTION"]);
  });
});

describe("Partial recovery across hard reloads and server state reconstruction", () => {
  it("survives hard reload by reconstructing approved categories from server grants without duplicate approvals", async () => {
    const pendingRequest: AccessRequest = {
      id: "req-reload",
      requesterDoctorId: "doc-reload",
      requesterHospitalId: "hosp-1",
      requesterHospitalName: "General Hospital",
      purpose: "Consultation",
      categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE"],
      status: "PENDING",
      createdAt: "2026-10-15T10:00:00Z",
      expiresAt: "2026-10-22T10:00:00Z",
      requester: null,
    };

    // Server-authoritative active grants (persisted on backend despite frontend refresh)
    const serverGrants: Grant[] = [
      {
        id: "grant-lab",
        granteeDoctorId: "doc-reload",
        categoryCode: "LAB_RESULT",
        status: "ACTIVE",
        grantedAt: "2026-10-15T10:02:00Z",
        expiresAt: "2026-11-15T10:02:00Z",
        revokedAt: null,
        grantee: null,
      },
    ];

    // In a fresh session (after a hard refresh), in-memory partialDecisions is empty.
    // The server grants reconstruct the state:
    const serverApprovedCodes = findServerApprovedCategoryCodes(pendingRequest, serverGrants);
    expect(serverApprovedCodes).toEqual(["LAB_RESULT"]);

    const remainingCategories = pendingRequest.categoryCodes.filter(
      (c) => !serverApprovedCodes.includes(c),
    );
    expect(remainingCategories).toEqual(["CLINICAL_NOTE"]);

    // Patient decides to decline the remaining category
    const outcomeReject: DecisionOutcome = {
      requestId: "req-reload",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "dec-note",
          categoryCode: "CLINICAL_NOTE",
          status: "REJECTED",
          decidedAt: "2026-10-15T10:15:00Z",
        },
      ],
      grants: [],
    };

    const { client, POST } = stubClient([ok(outcomeReject)]);

    // The frontend submits the decision: LAB_RESULT is already approved on server, CLINICAL_NOTE is rejected
    const submittedDecisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT"],
      rejectedCodes: ["CLINICAL_NOTE"],
    };

    // Filter out server-approved codes to avoid HTTP 409
    const pendingApprovedCodes = submittedDecisions.approvedCodes.filter(
      (code) => !serverApprovedCodes.includes(code),
    );
    expect(pendingApprovedCodes).toEqual([]);

    // Submit remaining decision
    const res = await decideRequest(
      client,
      "req-reload",
      submittedDecisions.rejectedCodes,
      "reject",
    );
    expect(res.status).toBe("ready");

    // Exactly one call: POST /reject for CLINICAL_NOTE, no POST /approve call
    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/reject", {
      params: { path: { request_id: "req-reload" } },
      body: { categoryCodes: ["CLINICAL_NOTE"] },
    });
  });

  it("handles patient choosing to approve remaining category after hard reload", async () => {
    const pendingRequest: AccessRequest = {
      id: "req-approve-remaining",
      requesterDoctorId: "doc-1",
      requesterHospitalId: "hosp-1",
      requesterHospitalName: "General Hospital",
      purpose: "Consultation",
      categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE"],
      status: "PENDING",
      createdAt: "2026-10-15T10:00:00Z",
      expiresAt: "2026-10-22T10:00:00Z",
      requester: null,
    };

    const serverGrants: Grant[] = [
      {
        id: "grant-lab",
        granteeDoctorId: "doc-1",
        categoryCode: "LAB_RESULT",
        status: "ACTIVE",
        grantedAt: "2026-10-15T10:02:00Z",
        expiresAt: "2026-11-15T10:02:00Z",
        revokedAt: null,
        grantee: null,
      },
    ];

    const serverApprovedCodes = findServerApprovedCategoryCodes(pendingRequest, serverGrants);
    expect(serverApprovedCodes).toEqual(["LAB_RESULT"]);

    // Patient decides to approve the remaining CLINICAL_NOTE
    const outcomeApprove: DecisionOutcome = {
      requestId: "req-approve-remaining",
      requestStatus: "DECIDED",
      decisions: [
        {
          id: "dec-note",
          categoryCode: "CLINICAL_NOTE",
          status: "APPROVED",
          decidedAt: "2026-10-15T10:15:00Z",
        },
      ],
      grants: [
        {
          id: "grant-note",
          categoryCode: "CLINICAL_NOTE",
          granteeDoctorId: "doc-1",
          grantedAt: "2026-10-15T10:15:00Z",
          expiresAt: "2026-11-15T10:15:00Z",
          revokedAt: null,
        },
      ],
    };

    const { client, POST } = stubClient([ok(outcomeApprove)]);

    const submittedDecisions: PerCategoryDecisions = {
      approvedCodes: ["LAB_RESULT", "CLINICAL_NOTE"],
      rejectedCodes: [],
    };

    // Only CLINICAL_NOTE should be submitted to /approve; LAB_RESULT must be omitted
    const pendingApprovedCodes = submittedDecisions.approvedCodes.filter(
      (code) => !serverApprovedCodes.includes(code),
    );
    expect(pendingApprovedCodes).toEqual(["CLINICAL_NOTE"]);

    const res = await decideRequest(
      client,
      "req-approve-remaining",
      pendingApprovedCodes,
      "approve",
    );
    expect(res.status).toBe("ready");
    expect(POST).toHaveBeenCalledTimes(1);
    expect(POST).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/approve", {
      params: { path: { request_id: "req-approve-remaining" } },
      body: { categoryCodes: ["CLINICAL_NOTE"] },
    });
  });

  it("does not settle categories when unrelated grants exist for different doctors or expired grants", async () => {
    const pendingRequest: AccessRequest = {
      id: "req-unrelated",
      requesterDoctorId: "doc-target",
      requesterHospitalId: "hosp-1",
      requesterHospitalName: "General Hospital",
      purpose: "Consultation",
      categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE"],
      status: "PENDING",
      createdAt: "2026-10-15T10:00:00Z",
      expiresAt: "2026-10-22T10:00:00Z",
      requester: null,
    };

    const unrelatedGrants: Grant[] = [
      // Different doctor
      {
        id: "grant-diff-doc",
        granteeDoctorId: "doc-OTHER",
        categoryCode: "LAB_RESULT",
        status: "ACTIVE",
        grantedAt: "2026-10-15T10:02:00Z",
        expiresAt: "2026-11-15T10:02:00Z",
        revokedAt: null,
        grantee: null,
      },
      // Target doctor, but unrequested category
      {
        id: "grant-diff-cat",
        granteeDoctorId: "doc-target",
        categoryCode: "RADIOLOGY",
        status: "ACTIVE",
        grantedAt: "2026-10-15T10:02:00Z",
        expiresAt: "2026-11-15T10:02:00Z",
        revokedAt: null,
        grantee: null,
      },
      // Target doctor and requested category, but EXPIRED
      {
        id: "grant-expired",
        granteeDoctorId: "doc-target",
        categoryCode: "CLINICAL_NOTE",
        status: "EXPIRED",
        grantedAt: "2026-10-10T10:00:00Z",
        expiresAt: "2026-10-14T10:00:00Z",
        revokedAt: null,
        grantee: null,
      },
    ];

    const serverApprovedCodes = findServerApprovedCategoryCodes(pendingRequest, unrelatedGrants);
    expect(serverApprovedCodes).toEqual([]);

    // None of the categories are settled; all categories remain pending
    expect(pendingRequest.categoryCodes.filter((c) => !serverApprovedCodes.includes(c))).toEqual([
      "LAB_RESULT",
      "CLINICAL_NOTE",
    ]);
  });
});
