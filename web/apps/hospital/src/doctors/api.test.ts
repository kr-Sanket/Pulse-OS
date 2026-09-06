import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { activateDoctor, deactivateDoctor, listDoctors, MAX_PAGE_SIZE } from "./api";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function stubClient(result: StubResult | Error) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return {
    client: { GET: call, POST: call } as unknown as PulseOSClient,
    call,
  };
}

const SIGNAL = new AbortController().signal;
const DOCTOR_ID = "11111111-1111-4111-8111-111111111111";

test("the roster is asked for a full page and passes the abort signal", async () => {
  const page = { items: [], nextCursor: null };
  const { client, call } = stubClient({ data: page, response: { status: 200 } });

  expect(await listDoctors(client, SIGNAL)).toEqual({ status: "ready", data: page });
  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me/doctors", {
    params: { query: { limit: MAX_PAGE_SIZE } },
    signal: SIGNAL,
  });
});

test("no hospital on the account is reported, not swallowed", async () => {
  const { client } = stubClient({ error: {}, response: { status: 404 } });

  expect(await listDoctors(client, SIGNAL)).toEqual({
    status: "error",
    message: "No hospital is attached to this account yet.",
  });
});

test("activating targets the doctor by id", async () => {
  const updated = { id: DOCTOR_ID, status: "ACTIVE" };
  const { client, call } = stubClient({ data: updated, response: { status: 200 } });

  expect(await activateDoctor(client, DOCTOR_ID)).toEqual({ status: "ready", data: updated });
  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me/doctors/{doctor_id}/activate", {
    params: { path: { doctor_id: DOCTOR_ID } },
  });
});

test("suspending targets the doctor by id", async () => {
  const updated = { id: DOCTOR_ID, status: "DISABLED" };
  const { client, call } = stubClient({ data: updated, response: { status: 200 } });

  expect(await deactivateDoctor(client, DOCTOR_ID)).toEqual({ status: "ready", data: updated });
  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me/doctors/{doctor_id}/deactivate", {
    params: { path: { doctor_id: DOCTOR_ID } },
  });
});

test("a 404 on an action does not claim to know which doctor it was", async () => {
  // The API answers 404 for an unknown doctor AND for another hospital's doctor,
  // deliberately indistinguishably, so the wording must not pick one.
  const { client } = stubClient({ error: {}, response: { status: 404 } });

  expect(await activateDoctor(client, DOCTOR_ID)).toEqual({
    status: "error",
    message: "That doctor is not on your hospital's roster. Reload the list.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await listDoctors(client, SIGNAL)).status).toBe("error");
  expect((await deactivateDoctor(client, DOCTOR_ID)).status).toBe("error");
});
