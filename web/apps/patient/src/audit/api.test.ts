import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { listAuditEvents } from "./api";

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

test("the trail is fetched as a full page", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  const result = await listAuditEvents(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: PAGE });
  expect(call).toHaveBeenCalledWith("/api/v1/audit-logs", {
    params: { query: { limit: 100 } },
    signal: SIGNAL,
  });
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
