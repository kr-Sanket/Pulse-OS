import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import { toFormData } from "@pulseos/ui";

import { uploadRecordForHealthId } from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function stubClient(result: StubResult | Error) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { client: { POST: call } as unknown as PulseOSClient, call };
}

const FILE = new File(["x"], "report.pdf", { type: "application/pdf" });

const UPLOAD = {
  patientHealthId: "PHI-IND-2026-7K3M99X",
  file: FILE,
  categoryCode: "CBC",
  dateOfService: "2026-07-01",
  description: "Routine bloods",
};

test("the upload is sent as multipart, carrying the patient's Health ID", async () => {
  const { client, call } = stubClient({ data: { id: "rec-1" }, response: { status: 201 } });

  await uploadRecordForHealthId(client, UPLOAD);

  expect(call).toHaveBeenCalledWith("/api/v1/records", {
    body: {
      patientHealthId: "PHI-IND-2026-7K3M99X",
      categoryCode: "CBC",
      dateOfService: "2026-07-01",
      description: "Routine bloods",
      file: FILE,
    },
    bodySerializer: toFormData,
  });
});

test("the shared serialiser puts the real File on the form and drops absent fields", () => {
  const form = toFormData({ file: FILE, categoryCode: "CBC", description: null });

  expect(form.get("file")).toBe(FILE);
  expect(form.get("categoryCode")).toBe("CBC");
  // A null description must be absent, not the string "null".
  expect(form.has("description")).toBe(false);
});

test("an unverified hospital is told why, not given a generic failure", async () => {
  const { client } = stubClient({ error: {}, response: { status: 409 } });

  expect(await uploadRecordForHealthId(client, UPLOAD)).toEqual({
    status: "error",
    message: "Your hospital is not verified yet, so it cannot upload records.",
  });
});

test("an unknown Health ID surfaces as something the administrator can act on", async () => {
  // The API answers 422 for a Health ID that matches no patient, as well as for a bad
  // category or date — so the wording names all three rather than guessing.
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  expect((await uploadRecordForHealthId(client, UPLOAD)).status).toBe("error");
});

test("a rejected file type and an oversized file each get their own wording", async () => {
  const tooLarge = stubClient({ error: {}, response: { status: 413 } });
  const wrongType = stubClient({ error: {}, response: { status: 415 } });

  expect(await uploadRecordForHealthId(tooLarge.client, UPLOAD)).toEqual({
    status: "error",
    message: "That file is larger than the upload limit.",
  });
  expect(await uploadRecordForHealthId(wrongType.client, UPLOAD)).toEqual({
    status: "error",
    message: "That file type is not accepted. Upload a PDF, JPEG or PNG.",
  });
});

test("a storage outage says nothing was uploaded, because nothing was", async () => {
  // The service writes the metadata row then the object, and rolls the row back if storage
  // fails — so "nothing was uploaded" is literally true.
  const { client } = stubClient({ error: {}, response: { status: 503 } });

  expect(await uploadRecordForHealthId(client, UPLOAD)).toEqual({
    status: "error",
    message: "Storage is unavailable right now — nothing was uploaded.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await uploadRecordForHealthId(client, UPLOAD)).status).toBe("error");
});
