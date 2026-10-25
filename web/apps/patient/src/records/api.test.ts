import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import {
  createDownloadUrl,
  exportFhirBundle,
  FHIR_JSON_TYPE,
  fhirExportFilename,
  getRecord,
  listCategories,
  listRecords,
  RECORDS_PAGE_SIZE,
  setRecordVisibility,
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
  return { client: { GET: call, POST: call, PATCH: call } as unknown as PulseOSClient, call };
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

test("hiding a record PATCHes its visibility sub-resource and names no patient", async () => {
  const { client, call } = stubClient(ok({ id: "rec-1", isHidden: true }));

  const result = await setRecordVisibility(client, "rec-1", true);

  // Exact match, so the absence of a patient identifier is part of what is asserted:
  // ownership comes from the token, and an extra key in the body would fail this.
  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}/visibility", {
    params: { path: { record_id: "rec-1" } },
    body: { isHidden: true },
  });
  expect(result).toEqual({ status: "ready", data: { id: "rec-1", isHidden: true } });
});

test("unhiding sends the state the caller wants rather than a verb", async () => {
  const { client, call } = stubClient(ok({ id: "rec-1", isHidden: false }));

  await setRecordVisibility(client, "rec-1", false);

  expect(call).toHaveBeenCalledWith("/api/v1/records/{record_id}/visibility", {
    params: { path: { record_id: "rec-1" } },
    body: { isHidden: false },
  });
});

test("a 404 reads as the record being gone rather than as a permission problem", async () => {
  const { client } = stubClient(fail(404));

  const result = await setRecordVisibility(client, "rec-1", true);

  expect(result).toEqual({
    status: "error",
    message: "That record is no longer available.",
  });
});

test("the fallback wording names the direction that failed", async () => {
  const hiding = await setRecordVisibility(stubClient(fail(500)).client, "rec-1", true);
  const unhiding = await setRecordVisibility(stubClient(fail(500)).client, "rec-1", false);

  expect(hiding).toEqual({ status: "error", message: "Could not hide this record." });
  expect(unhiding).toEqual({ status: "error", message: "Could not unhide this record." });
});

test("the API's own problem detail wins over the fallback", async () => {
  const { client } = stubClient(fail(403, { detail: "Your account is suspended." }));

  const result = await setRecordVisibility(client, "rec-1", true);

  expect(result).toEqual({ status: "error", message: "Your account is suspended." });
});

test("a rejected fetch becomes an error result rather than a thrown exception", async () => {
  const { client } = stubClient(new Error("offline"));

  const result = await setRecordVisibility(client, "rec-1", true);

  expect(result.status).toBe("error");
});

// -- FHIR export ------------------------------------------------------------------------

const EXPORT_DAY = new Date("2026-10-25T09:30:00Z");

test("the export asks for a blob and sends no patient identifier", async () => {
  const bundle = new Blob(['{"resourceType":"Bundle"}'], { type: FHIR_JSON_TYPE });
  const { client, call } = stubClient(ok(bundle));

  const result = await exportFhirBundle(client, EXPORT_DAY);

  expect(call).toHaveBeenCalledWith("/api/v1/records/export/fhir", { parseAs: "blob" });
  expect(result).toEqual({
    status: "ready",
    data: { blob: bundle, filename: "pulseos-fhir-export-2026-10-25.json" },
  });
});

test("the saved bundle is byte-for-byte the API body, typed as FHIR JSON", async () => {
  const body = '{"resourceType":"Bundle","type":"collection","entry":[]}';
  const { client } = stubClient(ok(new Blob([body])));

  const result = await exportFhirBundle(client, EXPORT_DAY);

  if (result.status !== "ready") throw new Error("expected a ready export");
  expect(result.data.blob.type).toBe(FHIR_JSON_TYPE);
  expect(await result.data.blob.text()).toBe(body);
});

test("export failures prefer the API detail and fall back per status", async () => {
  const withDetail = stubClient(fail(403, { detail: "Account is suspended." }));
  expect(await exportFhirBundle(withDetail.client, EXPORT_DAY)).toEqual({
    status: "error",
    message: "Account is suspended.",
  });

  const expired = stubClient(fail(401));
  expect(await exportFhirBundle(expired.client, EXPORT_DAY)).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to export your records.",
  });

  const storage = stubClient(fail(503));
  const storageResult = await exportFhirBundle(storage.client, EXPORT_DAY);
  expect(storageResult.status).toBe("error");
});

test("an unreachable API is a network failure, not a crash", async () => {
  const { client } = stubClient(new Error("offline"));
  const result = await exportFhirBundle(client, EXPORT_DAY);
  expect(result.status).toBe("error");
});

test("the export filename is dated in UTC", () => {
  expect(fhirExportFilename(new Date("2026-01-02T23:59:59Z"))).toBe(
    "pulseos-fhir-export-2026-01-02.json",
  );
});
