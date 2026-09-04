import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { createDownloadUrl, getRecord } from "./api";

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
const RECORD_ID = "8f1c2f4e-0f2b-4a2a-9a1e-9b0c1d2e3f40";

/** The one message that must cover four different truths without picking one. */
const UNAVAILABLE =
  "This record is not available to you. The patient may have withdrawn your access, the " +
  "grant may have expired, or the document may have been hidden.";

// -- reading the record ----------------------------------------------------------------------

test("the metadata read addresses the record by id and carries the caller's signal", async () => {
  const record = { id: RECORD_ID, originalFilename: "cbc.pdf" };
  const { client, call } = stubClient({ data: record, response: { status: 200 } });

  const result = await getRecord(client, RECORD_ID, SIGNAL);

  expect(result).toEqual({ status: "ready", data: record });
  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}", {
    params: { path: { record_id: RECORD_ID } },
    signal: SIGNAL,
  });
});

test("a revoked grant reads as 404, and the wording never claims which cause it was", async () => {
  // The API answers 404 rather than 403 so refusal is indistinguishable from absence
  // (docs/API_GUIDELINES.md); the message must not resolve the ambiguity for it.
  const { client } = stubClient({ error: {}, response: { status: 404 } });

  const result = await getRecord(client, RECORD_ID, SIGNAL);

  expect(result).toEqual({ status: "error", message: UNAVAILABLE });
  expect(UNAVAILABLE).toContain("withdrawn");
  expect(UNAVAILABLE).toContain("expired");
  expect(UNAVAILABLE).toContain("hidden");
});

test("reading maps each failure the endpoint declares", async () => {
  const wording: Readonly<Record<number, string>> = {
    401: "Your session has expired. Sign in again to continue.",
    403: "Your clinician profile is not active at its hospital.",
    404: UNAVAILABLE,
  };

  for (const [status, message] of Object.entries(wording)) {
    const { client } = stubClient({ error: {}, response: { status: Number(status) } });

    expect(await getRecord(client, RECORD_ID, SIGNAL)).toEqual({ status: "error", message });
  }
});

test("the API's own problem detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "Record not found." },
    response: { status: 404 },
  });

  expect(await getRecord(client, RECORD_ID, SIGNAL)).toEqual({
    status: "error",
    message: "Record not found.",
  });
});

test("an unmapped read failure still says something true", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await getRecord(client, RECORD_ID, SIGNAL)).toMatchObject({
    message: "Could not load this record.",
  });
});

// -- downloading ------------------------------------------------------------------------------

test("the download posts to the record's own sub-resource and sends no signal", async () => {
  const link = { url: "https://minio.local/records/abc?sig=1", expiresInSeconds: 300 };
  const { client, call } = stubClient({ data: link, response: { status: 200 } });

  const result = await createDownloadUrl(client, RECORD_ID);

  expect(result).toEqual({ status: "ready", data: link });
  // No signal: the server audits the download the moment it issues the link, so aborting
  // client-side would not unsay it.
  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}/download-url", {
    params: { path: { record_id: RECORD_ID } },
  });
});

test("download maps each failure the endpoint declares, storage included", async () => {
  const wording: Readonly<Record<number, string>> = {
    401: "Your session has expired. Sign in again, then download the file.",
    403: "Your clinician profile is not active at its hospital.",
    404: UNAVAILABLE,
    503: "File storage is unavailable right now. Nothing was downloaded; try again shortly.",
  };

  for (const [status, message] of Object.entries(wording)) {
    const { client } = stubClient({ error: {}, response: { status: Number(status) } });

    expect(await createDownloadUrl(client, RECORD_ID)).toEqual({ status: "error", message });
  }
});

test("an unmapped download failure still says something true", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await createDownloadUrl(client, RECORD_ID)).toMatchObject({
    message: "Could not prepare the download.",
  });
});

test("a rejected fetch is an error result on both calls, not a throw", async () => {
  const failing = stubClient(new Error("network down"));

  expect((await getRecord(failing.client, RECORD_ID, SIGNAL)).status).toBe("error");
  expect((await createDownloadUrl(failing.client, RECORD_ID)).status).toBe("error");
});
