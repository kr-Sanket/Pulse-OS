import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { loadDoctorProfile } from "./api";

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

test("a clinician profile comes back as registered", async () => {
  const profile = { fullName: "Dr Meera Sharma", status: "ACTIVE" };
  const { client } = stubClient({ data: profile, response: { status: 200 } });

  expect(await loadDoctorProfile(client, SIGNAL)).toEqual({
    status: "ready",
    data: { kind: "registered", profile },
  });
});

test("no clinician profile is an outcome, not an error — it routes to onboarding", async () => {
  for (const status of [403, 404]) {
    const { client } = stubClient({ error: {}, response: { status } });

    expect(await loadDoctorProfile(client, SIGNAL)).toEqual({
      status: "ready",
      data: { kind: "unregistered" },
    });
  }
});

test("a pre-registration Firebase token is refreshed and retried before onboarding", async () => {
  const profile = { fullName: "Dr Meera Sharma", status: "ACTIVE" };
  const get = vi
    .fn()
    .mockResolvedValueOnce({ error: {}, response: { status: 403 } })
    .mockResolvedValueOnce({ data: profile, response: { status: 200 } });
  const refreshToken = vi.fn().mockResolvedValue(undefined);
  const client = { GET: get } as unknown as PulseOSClient;

  expect(await loadDoctorProfile(client, SIGNAL, refreshToken)).toEqual({
    status: "ready",
    data: { kind: "registered", profile },
  });
  expect(refreshToken).toHaveBeenCalledOnce();
  expect(get).toHaveBeenCalledTimes(2);
});

test("a still-unprovisioned account is routed to onboarding after one refresh", async () => {
  const get = vi
    .fn()
    .mockResolvedValueOnce({ error: {}, response: { status: 403 } })
    .mockResolvedValueOnce({ error: {}, response: { status: 403 } });
  const refreshToken = vi.fn().mockResolvedValue(undefined);
  const client = { GET: get } as unknown as PulseOSClient;

  expect(await loadDoctorProfile(client, SIGNAL, refreshToken)).toEqual({
    status: "ready",
    data: { kind: "unregistered" },
  });
  expect(refreshToken).toHaveBeenCalledOnce();
});

test("an expired session is still a genuine error", async () => {
  const { client } = stubClient({ error: {}, response: { status: 401 } });

  expect(await loadDoctorProfile(client, SIGNAL)).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to continue.",
  });
});

test("server trouble is an error, never mistaken for an unregistered account", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await loadDoctorProfile(client, SIGNAL)).toMatchObject({
    status: "error",
    message: "Could not load your clinician profile.",
  });
});

test("a rejected fetch is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  expect((await loadDoctorProfile(client, SIGNAL)).status).toBe("error");
});
