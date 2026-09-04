import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import {
  createAccessRequest,
  listSentRequests,
  MAX_CATEGORIES_PER_REQUEST,
  MAX_HEALTH_ID_LENGTH,
  MAX_PAGE_SIZE,
  MAX_PURPOSE_LENGTH,
} from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function stubClient(result: StubResult | Error) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { client: { GET: call, POST: call } as unknown as PulseOSClient, call };
}

const SIGNAL = new AbortController().signal;
const HEALTH_ID = "PHI-IND-2026-1QE8DVR";
const DRAFT = {
  patientHealthId: HEALTH_ID,
  categoryCodes: ["CBC", "MRI"],
  purpose: "Cardiology consultation",
};

// -- createAccessRequest ------------------------------------------------------------------

test("creating a request posts the draft exactly as given", async () => {
  const created = { id: "req-1", status: "PENDING" };
  const { client, call } = stubClient({ data: created, response: { status: 201 } });

  const result = await createAccessRequest(client, DRAFT);

  expect(result).toEqual({ status: "ready", data: created });
  expect(call).toHaveBeenCalledWith("/api/v1/access-requests", {
    body: {
      patientHealthId: HEALTH_ID,
      categoryCodes: ["CBC", "MRI"],
      purpose: "Cardiology consultation",
    },
  });
});

test("the category codes are copied, so a caller's array cannot mutate the sent body", async () => {
  const codes = ["CBC"];
  const { client, call } = stubClient({ data: {}, response: { status: 201 } });

  await createAccessRequest(client, { ...DRAFT, categoryCodes: codes });
  codes.push("MRI");

  // The recorded body still holds the one-item copy taken at call time.
  expect(call).toHaveBeenCalledWith("/api/v1/access-requests", {
    body: {
      patientHealthId: HEALTH_ID,
      categoryCodes: ["CBC"],
      purpose: "Cardiology consultation",
    },
  });
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "Unknown patient Health ID." },
    response: { status: 422 },
  });

  const result = await createAccessRequest(client, DRAFT);

  expect(result).toEqual({ status: "error", message: "Unknown patient Health ID." });
});

test("a suspended clinician is told why the request was refused", async () => {
  const { client } = stubClient({ error: {}, response: { status: 403 } });

  const result = await createAccessRequest(client, DRAFT);

  expect(result).toEqual({
    status: "error",
    message: "Your clinician profile is not active at its hospital, so you cannot request access.",
  });
});

test("a clinician with no profile is told to finish registering", async () => {
  const { client } = stubClient({ error: {}, response: { status: 404 } });

  expect(await createAccessRequest(client, DRAFT)).toMatchObject({
    message: "No clinician profile is attached to this account yet.",
  });
});

test("a validation refusal points at the two fields that can cause it", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  expect(await createAccessRequest(client, DRAFT)).toMatchObject({
    message: "Check the Pulse Health ID and the categories you selected, then try again.",
  });
});

test("an expired session is named as such rather than as a generic failure", async () => {
  const { client } = stubClient({ error: {}, response: { status: 401 } });

  expect(await createAccessRequest(client, DRAFT)).toMatchObject({
    message: "Your session has expired. Sign in again, then send this request.",
  });
});

test("an unmapped status falls back to the call's own wording", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await createAccessRequest(client, DRAFT)).toEqual({
    status: "error",
    message: "Could not send this access request.",
  });
});

test("a rejected fetch is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await createAccessRequest(client, DRAFT);

  expect(result.status).toBe("error");
});

// -- listSentRequests ---------------------------------------------------------------------

test("the listing is fetched as a full page", async () => {
  const page = { items: [], nextCursor: null };
  const { client, call } = stubClient({ data: page, response: { status: 200 } });

  const result = await listSentRequests(client, SIGNAL);

  expect(result).toEqual({ status: "ready", data: page });
  expect(call).toHaveBeenCalledWith("/api/v1/access-requests/sent", {
    params: { query: { limit: MAX_PAGE_SIZE } },
    signal: SIGNAL,
  });
});

test("an empty listing is a success, not a failure", async () => {
  const { client } = stubClient({
    data: { items: [], nextCursor: null },
    response: { status: 200 },
  });

  expect(await listSentRequests(client, SIGNAL)).toEqual({
    status: "ready",
    data: { items: [], nextCursor: null },
  });
});

test("a listing failure has its own wording, distinct from the create path", async () => {
  const { client } = stubClient({ error: {}, response: { status: 401 } });

  expect(await listSentRequests(client, SIGNAL)).toMatchObject({
    message: "Your session has expired. Sign in again to see your requests.",
  });
});

test("a bad page request is reported as such", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  expect(await listSentRequests(client, SIGNAL)).toMatchObject({
    message: "That page of requests could not be loaded.",
  });
});

test("an aborted or offline listing is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("aborted"));

  expect((await listSentRequests(client, SIGNAL)).status).toBe("error");
});

// -- mirrored API limits ------------------------------------------------------------------

test("the mirrored limits match the backend contract", () => {
  expect(MAX_PAGE_SIZE).toBe(100);
  expect(MAX_CATEGORIES_PER_REQUEST).toBe(20);
  expect(MAX_PURPOSE_LENGTH).toBe(255);
  expect(MAX_HEALTH_ID_LENGTH).toBe(20);
});
