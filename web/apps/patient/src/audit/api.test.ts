import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { AUDIT_PAGE_SIZE, getBatchAnchor, listAuditEvents } from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function stubClient(result: StubResult | Error) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { client: { GET: call } as unknown as PulseOSClient, call };
}

const SIGNAL = new AbortController().signal;
const PAGE = { items: [], nextCursor: null };

test("the trail is fetched a page at a time, with no cursor on the first request", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  const result = await listAuditEvents(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: PAGE });
  expect(call).toHaveBeenCalledWith("/api/v1/audit-logs", {
    params: { query: { limit: AUDIT_PAGE_SIZE, cursor: undefined } },
    signal: SIGNAL,
  });
});

test("a cursor is forwarded so Load more continues the trail", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  await listAuditEvents(client, SIGNAL, "opaque-token");

  expect(call).toHaveBeenCalledWith("/api/v1/audit-logs", {
    params: { query: { limit: AUDIT_PAGE_SIZE, cursor: "opaque-token" } },
    signal: SIGNAL,
  });
});

test("the page size is well under the API cap, because the page now pages", () => {
  expect(AUDIT_PAGE_SIZE).toBeLessThan(100);
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "Profile not found for this account." },
    response: { status: 404 },
  });

  const result = await listAuditEvents(client, SIGNAL);

  expect(result).toEqual({ status: "error", message: "Profile not found for this account." });
});

test("an error without a usable detail falls back to wording chosen by status", async () => {
  const { client } = stubClient({ error: {}, response: { status: 401 } });

  const result = await listAuditEvents(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to see your history.",
  });
});

test("a bad page request is reported as such", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  const result = await listAuditEvents(client, SIGNAL);

  expect(result).toMatchObject({ message: "That page of history could not be loaded." });
});

test("a rejected fetch (offline, or an aborted request) is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await listAuditEvents(client, SIGNAL);

  expect(result.status).toBe("error");
});

test("a batch's chain anchoring is read by batch number, and a 429 reads as throttling", async () => {
  const anchor = { batchNumber: 3 };
  const { client, call } = stubClient({ data: anchor, response: { status: 200 } });

  expect(await getBatchAnchor(client, 3, SIGNAL)).toEqual({ status: "ready", data: anchor });
  expect(call).toHaveBeenCalledWith("/api/v1/audit-batches/{batch_number}/anchor", {
    params: { path: { batch_number: 3 } },
    signal: SIGNAL,
  });

  const throttled = stubClient({ error: {}, response: { status: 429 } });
  const result = await getBatchAnchor(throttled.client, 3, SIGNAL);
  expect(result.status).toBe("error");
});
