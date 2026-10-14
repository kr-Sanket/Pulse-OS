import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { decideRequest, listInbox } from "./api";

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

function stubClient(result: StubResult | Error) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { client: { GET: call, POST: call } as unknown as PulseOSClient, call };
}

const SIGNAL = new AbortController().signal;
const PAGE = { items: [], nextCursor: null };

test("the inbox is fetched as a full page", async () => {
  const { client, call } = stubClient(ok(PAGE));

  const result = await listInbox(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: PAGE });
  expect(call).toHaveBeenCalledWith("/api/v1/access-requests/inbox", {
    params: { query: { limit: 100 } },
    signal: SIGNAL,
  });
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient(fail(404, { detail: "Profile not found for this account." }));

  const result = await listInbox(client, SIGNAL);

  expect(result).toEqual({ status: "error", message: "Profile not found for this account." });
});

test("an error without a usable detail falls back to wording chosen by status", async () => {
  const { client } = stubClient(fail(401));

  const result = await listInbox(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to see your requests.",
  });
});

test("approving posts the requested codes to the approve path, unaltered", async () => {
  const { client, call } = stubClient(ok({ requestId: "req-1", requestStatus: "DECIDED" }));

  await decideRequest(client, "req-1", ["CBC", "LAB_REPORT"], "approve");

  expect(call).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/approve", {
    params: { path: { request_id: "req-1" } },
    body: { categoryCodes: ["CBC", "LAB_REPORT"] },
  });
});

test("declining posts the same body to the reject path", async () => {
  const { client, call } = stubClient(ok({ requestId: "req-1", requestStatus: "DECIDED" }));

  await decideRequest(client, "req-1", ["CBC"], "reject");

  expect(call).toHaveBeenCalledWith("/api/v1/access-requests/{request_id}/reject", {
    params: { path: { request_id: "req-1" } },
    body: { categoryCodes: ["CBC"] },
  });
});

test("a conflict explains that the request has already been settled", async () => {
  const { client } = stubClient(fail(409));

  const result = await decideRequest(client, "req-1", ["CBC"], "approve");

  expect(result).toEqual({
    status: "error",
    message: "This request has already been answered, or it has expired.",
  });
});

test("a rejected 422 explains the category mismatch", async () => {
  const { client } = stubClient(fail(422));

  const result = await decideRequest(client, "req-1", ["CBC"], "reject");

  expect(result.status).toBe("error");
  expect(result).toMatchObject({
    message: "Those record categories are not the ones this request asked for.",
  });
});

test("a rejected fetch (offline, or an aborted request) is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await decideRequest(client, "req-1", ["CBC"], "approve");

  expect(result.status).toBe("error");
});

test("deciding a request updates the initiating UI with recorded outcome", async () => {
  const { client } = stubClient(ok({ requestId: "req-1", requestStatus: "DECIDED" }));

  const result = await decideRequest(client, "req-1", ["CBC"], "approve");
  expect(result.status).toBe("ready");
  if (result.status === "ready") {
    expect(result.data.requestStatus).toBe("DECIDED");
  }
});
