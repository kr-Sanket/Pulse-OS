import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { searchRecordExistence } from "./api";

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
const HEALTH_ID = "PHI-IND-2026-1QE8DVR";

test("the search sends the Health ID as a query parameter", async () => {
  const items = [{ code: "CBC", displayName: "Complete Blood Count" }];
  const { client, call } = stubClient({ data: { items }, response: { status: 200 } });

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result).toEqual({ status: "ready", data: { items } });
  expect(call).toHaveBeenCalledWith("/api/v1/records/existence", {
    params: { query: { patientHealthId: HEALTH_ID } },
    signal: SIGNAL,
  });
});

test("an empty result is a success, not a failure", async () => {
  const { client } = stubClient({ data: { items: [] }, response: { status: 200 } });

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result).toEqual({ status: "ready", data: { items: [] } });
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "Unknown patient Health ID." },
    response: { status: 422 },
  });

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result).toEqual({ status: "error", message: "Unknown patient Health ID." });
});

test("a suspended clinician is told why, not left guessing", async () => {
  const { client } = stubClient({ error: {}, response: { status: 403 } });

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your clinician profile is not active at its hospital.",
  });
});

test("an unmatched Health ID falls back to wording that reveals nothing extra", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result).toMatchObject({ message: "No patient matches that Pulse Health ID." });
});

test("a rejected fetch (offline, or an aborted request) is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await searchRecordExistence(client, HEALTH_ID, SIGNAL);

  expect(result.status).toBe("error");
});
