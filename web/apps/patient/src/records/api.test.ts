import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import {
  createDownloadUrl,
  getRecord,
  listCategories,
  listRecords,
  RECORDS_PAGE_SIZE,
  toFormData,
  uploadRecord,
} from "./api";

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

test("categories come back as a plain list", async () => {
  const { client } = stubClient(
    ok({ items: [{ code: "CBC", displayName: "Complete Blood Count" }] }),
  );

  const result = await listCategories(client, SIGNAL);

  expect(result).toEqual({
    status: "ready",
    data: [{ code: "CBC", displayName: "Complete Blood Count" }],
  });
});

const UNFILTERED = { category: null, search: null, sort: "newest" } as const;

test("the listing sends the sort and omits the filters that are not set", async () => {
  const { client, call } = stubClient(ok({ items: [], nextCursor: null }));

  await listRecords(client, UNFILTERED, SIGNAL);

  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    params: {
      query: {
        category: undefined,
        search: undefined,
        sort: "newest",
        cursor: undefined,
        limit: RECORDS_PAGE_SIZE,
      },
    },
    signal: SIGNAL,
  });
});

test("category, search and sort are all sent as query parameters", async () => {
  const { client, call } = stubClient(ok({ items: [], nextCursor: null }));

  await listRecords(client, { category: "MRI", search: "lipid", sort: "oldest" }, SIGNAL);

  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    params: {
      query: {
        category: "MRI",
        search: "lipid",
        sort: "oldest",
        cursor: undefined,
        limit: RECORDS_PAGE_SIZE,
      },
    },
    signal: SIGNAL,
  });
});

test("a cursor is forwarded so Load more continues the same sequence", async () => {
  const { client, call } = stubClient(ok({ items: [], nextCursor: null }));

  await listRecords(client, { ...UNFILTERED, cursor: "opaque-token" }, SIGNAL);

  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    params: {
      query: {
        category: undefined,
        search: undefined,
        sort: "newest",
        cursor: "opaque-token",
        limit: RECORDS_PAGE_SIZE,
      },
    },
    signal: SIGNAL,
  });
});

test("the page size is well under the API cap, because the page now pages", async () => {
  expect(RECORDS_PAGE_SIZE).toBeLessThan(100);
});

test("an RFC 7807 detail becomes the message shown to the patient", async () => {
  const { client } = stubClient(fail(404, { detail: "Patient profile not found." }));

  const result = await listRecords(client, UNFILTERED, SIGNAL);

  expect(result).toEqual({ status: "error", message: "Patient profile not found." });
});

test("an error without a usable detail falls back to per-call wording", async () => {
  const { client } = stubClient(fail(500));

  const result = await getRecord(client, "rec-1", SIGNAL);

  expect(result).toEqual({ status: "error", message: "Could not load this record." });
});

test("a rejected fetch (offline, or an aborted request) is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await listRecords(client, UNFILTERED, SIGNAL);

  expect(result.status).toBe("error");
});

test("a download answers with the presigned URL", async () => {
  const { client, call } = stubClient(
    ok({ url: "https://minio.test/signed", expiresInSeconds: 300 }),
  );

  const result = await createDownloadUrl(client, "rec-1");

  expect(result).toEqual({
    status: "ready",
    data: { url: "https://minio.test/signed", expiresInSeconds: 300 },
  });
  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}/download-url", {
    params: { path: { record_id: "rec-1" } },
  });
});

test("an upload is multipart, carries the file, and sends no Health ID", async () => {
  const file = new File(["scan"], "scan.pdf", { type: "application/pdf" });
  const { client, call } = stubClient(ok({ id: "rec-9" }, 201));

  await uploadRecord(client, {
    file,
    categoryCode: "CBC",
    dateOfService: "2026-08-24",
    description: null,
  });

  // Exact match: the absence of patientHealthId is part of the contract for a locker upload.
  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    body: { categoryCode: "CBC", dateOfService: "2026-08-24", description: null, file },
    bodySerializer: toFormData,
  });
});

test("the serializer keeps the File intact and drops empty optional fields", () => {
  const file = new File(["scan"], "scan.pdf", { type: "application/pdf" });

  const form = toFormData({ file, categoryCode: "CBC", description: null });

  expect(form.get("file")).toBe(file);
  expect(form.get("categoryCode")).toBe("CBC");
  expect(form.has("description")).toBe(false);
});

test("an upload refused without a detail gets wording chosen by status", async () => {
  const { client } = stubClient(fail(413));

  const result = await uploadRecord(client, {
    file: new File(["x"], "x.pdf", { type: "application/pdf" }),
    categoryCode: "CBC",
    dateOfService: "2026-08-24",
    description: null,
  });

  expect(result).toEqual({
    status: "error",
    message: "That file is larger than the upload limit.",
  });
});
