import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { getAuditProof, type AuditIntegrity, type AuditProof } from "./api";
import { actionPresentation, integrityView, LOCAL_MERKLE_BATCH_NETWORK, proofRows } from "./view";

const SIGNAL = new AbortController().signal;

function integrity(status: AuditIntegrity["status"], network: string | null): AuditIntegrity {
  return { status, network, reference: network === null ? null : "0xabc", anchoredAt: null };
}

test("a verified batched entry says verified, and says it is local, not a blockchain", () => {
  const view = integrityView(integrity("VERIFIED", LOCAL_MERKLE_BATCH_NETWORK));
  expect(view).toMatchObject({ status: "VERIFIED", tone: "success", batched: true });
  expect(view.label).toBe("Integrity verified");
  expect(view.detail).toMatch(/local Merkle batch/);
  expect(view.detail).toMatch(/Not anchored to a public blockchain/);
});

test("a legacy per-event anchor verifies but offers no Merkle proof", () => {
  const view = integrityView(integrity("VERIFIED", "local-dev"));
  expect(view.status).toBe("VERIFIED");
  expect(view.batched).toBe(false);
  expect(view.detail).not.toMatch(/Merkle/);
});

test("an unsealed entry is pending, never verified", () => {
  const view = integrityView(integrity("NOT_ANCHORED", null));
  expect(view).toMatchObject({ status: "NOT_ANCHORED", tone: "warning", batched: false });
  expect(view.label).not.toMatch(/verified/i);
});

test("both tamper verdicts read as a failed check, and keep the proof reachable", () => {
  for (const status of ["EVENT_ALTERED", "ANCHOR_ALTERED"] as const) {
    const view = integrityView(integrity(status, LOCAL_MERKLE_BATCH_NETWORK));
    expect(view.tone).toBe("destructive");
    expect(view.label).toBe("Integrity check failed");
    expect(view.batched).toBe(true);
  }
});

test("a missing or unknown verdict is unavailable, never verified", () => {
  expect(integrityView(null).status).toBe("UNKNOWN");
  expect(integrityView(undefined).label).toBe("Integrity unavailable");
  const unknown = integrityView({
    status: "SOMETHING_NEW" as AuditIntegrity["status"],
    network: LOCAL_MERKLE_BATCH_NETWORK,
    reference: null,
    anchoredAt: null,
  });
  expect(unknown.status).toBe("UNKNOWN");
  expect(unknown.tone).toBe("neutral");
});

test("the FHIR export action has its own label", () => {
  expect(actionPresentation("RECORD_EXPORTED")).toEqual({
    label: "Records exported (FHIR)",
    tone: "primary",
  });
});

const PROOF: AuditProof = {
  auditLogId: "evt-1",
  batchId: "batch-1",
  batchNumber: 3,
  commitment: "c".repeat(64),
  eventDigest: "e".repeat(64),
  isEventValid: true,
  isProofValid: false,
  leafCount: 5,
  leafIndex: 0,
  proof: null,
  proofStepsCount: 0,
  recomputedDigest: "e".repeat(64),
  root: "r".repeat(64),
  status: "ANCHOR_ALTERED",
};

test("proof rows report both checks and the batch position, one-based", () => {
  const rows = Object.fromEntries(proofRows(PROOF).map((row) => [row.label, row.value]));
  expect(rows["Batch"]).toBe("#3");
  expect(rows["Position"]).toBe("Leaf 1 of 5");
  expect(rows["Event digest matches"]).toBe("Yes");
  expect(rows["Inclusion proof valid"]).toBe("No");
  expect(rows["Batch Merkle root"]).toBe("r".repeat(64));
});

test("the proof is fetched for the entry's own id", async () => {
  const call = vi.fn(() => Promise.resolve({ data: PROOF, response: { status: 200 } }));
  const client = { GET: call } as unknown as PulseOSClient;

  const result = await getAuditProof(client, "evt-1", SIGNAL);

  expect(result).toEqual({ status: "ready", data: PROOF });
  expect(call).toHaveBeenCalledWith("/api/v1/audit-logs/{audit_log_id}/proof", {
    params: { path: { audit_log_id: "evt-1" } },
    signal: SIGNAL,
  });
});

test("an unsealed entry's 404 is explained, not shown as an error code", async () => {
  const call = vi.fn(() => Promise.resolve({ error: {}, response: { status: 404 } }));
  const client = { GET: call } as unknown as PulseOSClient;

  const result = await getAuditProof(client, "evt-1", SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "No integrity proof exists for this entry yet — it has not been sealed into a batch.",
  });
});
