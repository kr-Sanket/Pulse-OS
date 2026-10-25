import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";
import { ACCOUNT_SUSPENDED_MESSAGE } from "@pulseos/ui";

import { loadHospitalProfile } from "./api";

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

test("a hospital profile comes back as registered", async () => {
  const profile = { adminFullName: "Anita Rao", hospital: { hid: "HID-0001" } };
  const { client, call } = stubClient({ data: profile, response: { status: 200 } });

  expect(await loadHospitalProfile(client, SIGNAL)).toEqual({
    status: "ready",
    data: { kind: "registered", profile },
  });
  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me", { signal: SIGNAL });
});

test("no hospital is an outcome, not an error — it routes to onboarding", async () => {
  for (const status of [403, 404]) {
    const { client } = stubClient({ error: {}, response: { status } });

    expect(await loadHospitalProfile(client, SIGNAL)).toEqual({
      status: "ready",
      data: { kind: "unregistered" },
    });
  }
});

test("a pre-registration Firebase token is refreshed and retried before onboarding", async () => {
  const profile = { adminFullName: "Anita Rao", hospital: { hid: "HID-0001" } };
  const get = vi
    .fn()
    .mockResolvedValueOnce({ error: {}, response: { status: 403 } })
    .mockResolvedValueOnce({ data: profile, response: { status: 200 } });
  const refreshToken = vi.fn().mockResolvedValue(undefined);
  const client = { GET: get } as unknown as PulseOSClient;

  expect(await loadHospitalProfile(client, SIGNAL, refreshToken)).toEqual({
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

  expect(await loadHospitalProfile(client, SIGNAL, refreshToken)).toEqual({
    status: "ready",
    data: { kind: "unregistered" },
  });
  expect(refreshToken).toHaveBeenCalledOnce();
});

test("an expired session is still a genuine error", async () => {
  const { client } = stubClient({ error: {}, response: { status: 401 } });

  const result = await loadHospitalProfile(client, SIGNAL);

  expect(result).toEqual({
    status: "error",
    message: "Your session has expired. Sign in again to continue.",
  });
});

test("server trouble is an error, never mistaken for an unregistered account", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await loadHospitalProfile(client, SIGNAL)).toMatchObject({
    status: "error",
    message: "Could not load your hospital.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  const result = await loadHospitalProfile(client, SIGNAL);

  expect(result.status).toBe("error");
});

test("a suspended account is reported, never routed to onboarding or refreshed", async () => {
  const get = vi.fn().mockResolvedValue({
    error: { detail: "Account is suspended." },
    response: { status: 403 },
  });
  const refreshToken = vi.fn().mockResolvedValue(undefined);
  const client = { GET: get } as unknown as PulseOSClient;

  expect(await loadHospitalProfile(client, SIGNAL, refreshToken)).toEqual({
    status: "error",
    message: ACCOUNT_SUSPENDED_MESSAGE,
  });
  expect(refreshToken).not.toHaveBeenCalled();
  expect(get).toHaveBeenCalledOnce();
});

test("an account suspended between the refresh and the retry is still reported", async () => {
  const get = vi
    .fn()
    .mockResolvedValueOnce({ error: {}, response: { status: 403 } })
    .mockResolvedValueOnce({
      error: { detail: "Account is suspended." },
      response: { status: 403 },
    });
  const refreshToken = vi.fn().mockResolvedValue(undefined);
  const client = { GET: get } as unknown as PulseOSClient;

  expect(await loadHospitalProfile(client, SIGNAL, refreshToken)).toEqual({
    status: "error",
    message: ACCOUNT_SUSPENDED_MESSAGE,
  });
});
