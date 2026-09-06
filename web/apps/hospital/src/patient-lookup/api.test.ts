import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { lookupPatient } from "./api";

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
const HEALTH_ID = "PHI-IND-2026-7K3M99X";

test("a found patient comes back as the two-field identity and nothing else", () => {
  const patient = { healthId: HEALTH_ID, fullName: "Asha Rao" };

  expect(Object.keys(patient).sort()).toEqual(["fullName", "healthId"]);
});

test("the lookup queries by Health ID and passes the abort signal", async () => {
  const patient = { healthId: HEALTH_ID, fullName: "Asha Rao" };
  const { client, call } = stubClient({ data: patient, response: { status: 200 } });

  expect(await lookupPatient(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "ready",
    data: patient,
  });
  expect(call).toHaveBeenCalledWith("/api/v1/patients/lookup", {
    params: { query: { healthId: HEALTH_ID } },
    signal: SIGNAL,
  });
});

test("the backend's own 422 sentence is preferred over the portal's fallback", async () => {
  // The API states "not a valid Health ID" and "no patient has that ID" apart, and that
  // distinction is the point of ADR-012's check character — it must reach the operator.
  const { client } = stubClient({
    error: { detail: "That is not a valid Pulse Health ID." },
    response: { status: 422 },
  });

  expect(await lookupPatient(client, "PHI-IND-2026-AAAAAAA", SIGNAL)).toEqual({
    status: "error",
    message: "That is not a valid Pulse Health ID.",
  });
});

test("a 422 with no problem detail falls back to wording that fits both causes", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  expect(await lookupPatient(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "error",
    message: "That Pulse Health ID does not match a patient.",
  });
});

test("an expired session and a forbidden role each get their own wording", async () => {
  const expired = stubClient({ error: {}, response: { status: 401 } });
  const forbidden = stubClient({ error: {}, response: { status: 403 } });

  expect((await lookupPatient(expired.client, HEALTH_ID, SIGNAL)).status).toBe("error");
  expect(await lookupPatient(forbidden.client, HEALTH_ID, SIGNAL)).toEqual({
    status: "error",
    message: "This account cannot look patients up.",
  });
});

test("an unmapped status falls back rather than showing nothing", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await lookupPatient(client, HEALTH_ID, SIGNAL)).toEqual({
    status: "error",
    message: "Could not look this patient up.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await lookupPatient(client, HEALTH_ID, SIGNAL)).status).toBe("error");
});
