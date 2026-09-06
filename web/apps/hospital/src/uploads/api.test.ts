import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { createDownloadUrl, getUpload, listUploads, MAX_PAGE_SIZE } from "./api";

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
const RECORD_ID = "11111111-1111-4111-8111-111111111111";

// -- listing ------------------------------------------------------------------------------

test("the listing asks for a full page and passes the abort signal", async () => {
  const page = { items: [], nextCursor: null };
  const { client, call } = stubClient({ data: page, response: { status: 200 } });

  expect(await listUploads(client, SIGNAL)).toEqual({ status: "ready", data: page });
  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    params: { query: { limit: MAX_PAGE_SIZE } },
    signal: SIGNAL,
  });
});

test("no query narrows the listing to this hospital — the server decides the scope", async () => {
  const { client, call } = stubClient({
    data: { items: [], nextCursor: null },
    response: { status: 200 },
  });

  await listUploads(client, SIGNAL);

  const query = (call.mock.calls[0] as unknown[])[1] as { params: { query: object } };
  expect(Object.keys(query.params.query)).toEqual(["limit"]);
});

test("a cursor is only sent when one is given", async () => {
  const { client, call } = stubClient({
    data: { items: [], nextCursor: null },
    response: { status: 200 },
  });

  await listUploads(client, SIGNAL, "cursor-abc");

  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    params: { query: { limit: MAX_PAGE_SIZE, cursor: "cursor-abc" } },
    signal: SIGNAL,
  });
});

// -- HTTP status mapping -----------------------------------------------------------------

test("each listing status maps to wording an administrator can act on", async () => {
  const cases: [number, string][] = [
    [401, "Your session has expired. Sign in again to see your uploads."],
    [403, "This account cannot list records."],
    [404, "No hospital is attached to this account yet."],
    [422, "That page of uploads could not be loaded."],
  ];
  for (const [status, message] of cases) {
    const { client } = stubClient({ error: {}, response: { status } });

    expect(await listUploads(client, SIGNAL)).toEqual({ status: "error", message });
  }
});

test("an unmapped status falls back rather than showing nothing", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await listUploads(client, SIGNAL)).toEqual({
    status: "error",
    message: "Could not load your uploads.",
  });
});

// -- RFC 7807 precedence -------------------------------------------------------------------

test("the API's own problem detail wins over the portal's per-status wording", async () => {
  // The backend answers application/problem+json; when it has said something specific, that
  // sentence is more useful than anything hardcoded here.
  const { client } = stubClient({
    error: { detail: "Cursor is not valid for this listing." },
    response: { status: 422 },
  });

  expect(await listUploads(client, SIGNAL)).toEqual({
    status: "error",
    message: "Cursor is not valid for this listing.",
  });
});

test("the per-status wording is used only when no problem detail was sent", async () => {
  const { client } = stubClient({ error: { title: "Unprocessable" }, response: { status: 422 } });

  expect(await listUploads(client, SIGNAL)).toEqual({
    status: "error",
    message: "That page of uploads could not be loaded.",
  });
});

// -- reading one record ---------------------------------------------------------------------

test("the record read targets the record by id and passes the signal", async () => {
  const record = { id: RECORD_ID };
  const { client, call } = stubClient({ data: record, response: { status: 200 } });

  expect(await getUpload(client, RECORD_ID, SIGNAL)).toEqual({ status: "ready", data: record });
  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}", {
    params: { path: { record_id: RECORD_ID } },
    signal: SIGNAL,
  });
});

test("a 404 does not claim the record is gone, only that it is not yours", async () => {
  // 404 covers "no such record" and "another hospital's record" indistinguishably; naming
  // one would confirm the other exists.
  const { client } = stubClient({ error: {}, response: { status: 404 } });

  expect(await getUpload(client, RECORD_ID, SIGNAL)).toEqual({
    status: "error",
    message: "This record is not one of your hospital's uploads, so it cannot be opened here.",
  });
});

// -- download ------------------------------------------------------------------------------

test("the download link is requested without an abort signal", async () => {
  // Issuing the link IS the audited download, so abandoning the request would not unsay it.
  const { client, call } = stubClient({
    data: { url: "https://example.test/f", expiresInSeconds: 300 },
    response: { status: 200 },
  });

  await createDownloadUrl(client, RECORD_ID);

  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}/download-url", {
    params: { path: { record_id: RECORD_ID } },
  });
});

test("a storage outage says nothing was downloaded, because nothing was", async () => {
  const { client } = stubClient({ error: {}, response: { status: 503 } });

  expect(await createDownloadUrl(client, RECORD_ID)).toEqual({
    status: "error",
    message: "File storage is unavailable right now. Nothing was downloaded; try again shortly.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await listUploads(client, SIGNAL)).status).toBe("error");
  expect((await getUpload(client, RECORD_ID, SIGNAL)).status).toBe("error");
  expect((await createDownloadUrl(client, RECORD_ID)).status).toBe("error");
});
