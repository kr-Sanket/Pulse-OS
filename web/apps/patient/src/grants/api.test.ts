import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { listGrants, revokeGrant } from "./api";

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

test("the listing is fetched as a full page", async () => {
  const { client, call } = stubClient(ok(PAGE));

  const result = await listGrants(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: PAGE });
  expect(call).toHaveBeenCalledWith("/api/v1/consent-grants", {
    params: { query: { limit: 100 } },
    signal: SIGNAL,
  });
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient(fail(404, { detail: "Profile not found for this account." }));

  const result = await listGrants(client, SIGNAL);

  expect(result).toEqual({ status: "error", message: "Profile not found for this account." });
});

test("an error without a usable detail falls back to wording chosen by status", async () => {
  const { client } = stubClient(fail(401));

  const result = await listGrants(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to see who has access.",
  });
});

test("revoking posts to the grant's own path", async () => {
  const { client, call } = stubClient(ok({ id: "grant-1", revokedAt: "2026-09-03T12:00:00Z" }));

  const result = await revokeGrant(client, "grant-1");

  expect(result.status).toBe("ready");
  expect(call).toHaveBeenCalledWith("/api/v1/consent-grants/{grant_id}/revoke", {
    params: { path: { grant_id: "grant-1" } },
  });
});

test("a grant that is gone explains itself and suggests a refresh", async () => {
  const { client } = stubClient(fail(404));

  const result = await revokeGrant(client, "grant-1");

  expect(result).toEqual({
    status: "error",
    message: "This grant is no longer available. Refresh to see the current list.",
  });
});

test("a conflict is reported rather than swallowed", async () => {
  const { client } = stubClient(fail(409));

  const result = await revokeGrant(client, "grant-1");

  expect(result).toMatchObject({
    status: "error",
    message: "This grant could not be withdrawn in its current state.",
  });
});

test("a rejected fetch (offline, or an aborted request) is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await revokeGrant(client, "grant-1");

  expect(result.status).toBe("error");
});
