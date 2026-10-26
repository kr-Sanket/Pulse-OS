import { expect, test } from "vitest";

import type { BatchAnchor } from "./api";
import { chainAnchorView } from "./view";

const COMMITMENT = "7d2d9dd7205f9adb892bd361857652127df7e954f3132228e7724aeb53476c36";
const TX = `0x${"ab".repeat(32)}`;
const CONTRACT = "0x5FbDB2315678afecb367f032d93F642f64180aa3";

function anchor(overrides: Partial<BatchAnchor> = {}): BatchAnchor {
  return {
    batchNumber: 1,
    leafCount: 3,
    root: "9".repeat(64),
    commitment: COMMITMENT,
    localStatus: "VALID",
    network: "polygon-amoy",
    chainId: 80002,
    contractAddress: CONTRACT,
    explorerContractUrl: `https://amoy.polygonscan.com/address/${CONTRACT}`,
    anchor: {
      status: "CONFIRMED",
      txHash: TX,
      blockNumber: 42,
      blockTimestamp: "2026-10-26T12:00:00Z",
      submittedAt: "2026-10-26T11:59:00Z",
      confirmedAt: "2026-10-26T12:01:00Z",
      failureReason: null,
      explorerTxUrl: `https://amoy.polygonscan.com/tx/${TX}`,
    },
    chainVerification: {
      status: "VERIFIED",
      expectedCommitment: COMMITMENT,
      onChainBlockNumber: 42,
      checkedAt: "2026-10-26T12:05:00Z",
    },
    ...overrides,
  };
}

function rowValue(view: ReturnType<typeof chainAnchorView>, label: string) {
  return view.rows.find((row) => row.label === label)?.value;
}

test("a verified anchor shows the testnet, transaction, block and explorer links", () => {
  const view = chainAnchorView(anchor());
  expect(view).toMatchObject({ label: "Verified on-chain", tone: "success" });
  expect(rowValue(view, "Network")).toBe("Polygon Amoy testnet");
  expect(rowValue(view, "Transaction")).toBe(TX);
  expect(rowValue(view, "Block")).toBe("42");
  expect(rowValue(view, "Submission")).toBe("Confirmed");
  expect(rowValue(view, "Published commitment")).toBe(COMMITMENT);
  expect(view.explorerTxUrl).toBe(`https://amoy.polygonscan.com/tx/${TX}`);
  expect(view.explorerContractUrl).toContain(CONTRACT);
});

test("a stored confirmation is never shown as verified when the chain disagrees", () => {
  const view = chainAnchorView(
    anchor({
      chainVerification: {
        status: "MISMATCH",
        expectedCommitment: COMMITMENT,
        onChainBlockNumber: null,
        checkedAt: "2026-10-26T12:05:00Z",
      },
    }),
  );
  expect(view.label).toBe("On-chain mismatch");
  expect(view.tone).toBe("destructive");
});

test("pending, failed, unreachable and unconfigured states read honestly", () => {
  const pending = chainAnchorView(
    anchor({
      anchor: { ...anchor().anchor!, status: "PENDING", blockNumber: null, confirmedAt: null },
      chainVerification: {
        status: "NOT_ON_CHAIN",
        expectedCommitment: COMMITMENT,
        onChainBlockNumber: null,
        checkedAt: "2026-10-26T12:05:00Z",
      },
    }),
  );
  expect(pending.label).toBe("Not anchored yet");
  expect(rowValue(pending, "Submission")).toBe("Submitted, awaiting confirmation");

  const failed = chainAnchorView(
    anchor({
      anchor: {
        ...anchor().anchor!,
        status: "FAILED",
        txHash: null,
        failureReason: "rpc_unavailable",
        explorerTxUrl: null,
      },
      chainVerification: {
        status: "UNAVAILABLE",
        expectedCommitment: COMMITMENT,
        onChainBlockNumber: null,
        checkedAt: "2026-10-26T12:05:00Z",
      },
    }),
  );
  expect(failed.label).toBe("Chain unreachable");
  expect(rowValue(failed, "Failure reason")).toBe("rpc_unavailable");
  expect(rowValue(failed, "Transaction")).toBeUndefined();
  expect(failed.explorerTxUrl).toBeNull();

  const unconfigured = chainAnchorView(
    anchor({
      network: null,
      chainId: null,
      contractAddress: null,
      explorerContractUrl: null,
      anchor: null,
      chainVerification: {
        status: "NOT_CONFIGURED",
        expectedCommitment: COMMITMENT,
        onChainBlockNumber: null,
        checkedAt: "2026-10-26T12:05:00Z",
      },
    }),
  );
  expect(unconfigured.label).toBe("Not configured");
  expect(rowValue(unconfigured, "Submission")).toBe("Not submitted");
  expect(rowValue(unconfigured, "Network")).toBeUndefined();
});

test("a locally tampered batch is reported as a local failure", () => {
  const view = chainAnchorView(
    anchor({
      localStatus: "TAMPERED",
      chainVerification: {
        status: "LOCAL_INTEGRITY_FAILED",
        expectedCommitment: null,
        onChainBlockNumber: null,
        checkedAt: "2026-10-26T12:05:00Z",
      },
    }),
  );
  expect(view).toMatchObject({ label: "Local check failed", tone: "destructive" });
});

test("only http(s) explorer links are ever rendered", () => {
  const view = chainAnchorView(
    anchor({
      explorerContractUrl: "javascript:alert(1)",
      anchor: { ...anchor().anchor!, explorerTxUrl: "javascript:alert(1)" },
    }),
  );
  expect(view.explorerTxUrl).toBeNull();
  expect(view.explorerContractUrl).toBeNull();
});
