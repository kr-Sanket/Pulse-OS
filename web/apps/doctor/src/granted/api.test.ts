import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { listGrantedRecords, MAX_PAGE_SIZE } from "./api";

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
const PATIENT_ID = "00000000-0000-0000-0000-000000000001";
const PAGE = { patientId: PATIENT_ID, grantedCategories: [], items: [], nextCursor: null };

test("the listing asks for one full page of the named patient's records", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  const result = await listGrantedRecords(client, HEALTH_ID, SIGNAL);

  expect(result).toEqual({ status: "ready", data: PAGE });
  expect(call).toHaveBeenCalledWith("/api/v1/granted-records", {
    params: { query: { patientHealthId: HEALTH_ID, limit: MAX_PAGE_SIZE } },
    signal: SIGNAL,
  });
});

test("a cursor is sent only when there is one — never as an empty parameter", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  await listGrantedRecords(client, HEALTH_ID, SIGNAL, "opaque-cursor");

  expect(call).toHaveBeenCalledWith("/api/v1/granted-records", {
    params: {
      query: { patientHealthId: HEALTH_ID, limit: MAX_PAGE_SIZE, cursor: "opaque-cursor" },
    },
    signal: SIGNAL,
  });
});

test("holding no grant is a result, not a failure", async () => {
  // The API answers 200 with an empty scope rather than 403: the clinician already knows
  // this patient exists, so there is no existence left to protect.
  const { client } = stubClient({ data: PAGE, response: { status: 200 } });

  expect(await listGrantedRecords(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "ready",
    data: PAGE,
  });
});

test("the API's own problem detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "Your clinician profile is not active at its hospital." },
    response: { status: 403 },
  });

  expect(await listGrantedRecords(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "error",
    message: "Your clinician profile is not active at its hospital.",
  });
});

test("each failure the endpoint declares gets wording a clinician can act on", async () => {
  const wording: Readonly<Record<number, string>> = {
    401: "Your session has expired. Sign in again to continue.",
    403: "Your clinician profile is not active at its hospital.",
    404: "No clinician profile is attached to this account yet.",
    422: "No patient matches that Pulse Health ID.",
  };

  for (const [status, message] of Object.entries(wording)) {
    // FastAPI's 422 body is a field list rather than a sentence, so every one of these
    // arrives without a usable detail.
    const { client } = stubClient({ error: {}, response: { status: Number(status) } });

    expect(await listGrantedRecords(client, HEALTH_ID, SIGNAL)).toEqual({
      status: "error",
      message,
    });
  }
});

test("an unmapped status still says something true", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await listGrantedRecords(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "error",
    message: "Could not load the records you have been granted.",
  });
});

test("a rejected fetch is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  expect((await listGrantedRecords(client, HEALTH_ID, SIGNAL)).status).toBe("error");
});
