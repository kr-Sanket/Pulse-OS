import { expect, test, vi } from "vitest";

import type { PatientProfile, PulseOSClient } from "@pulseos/api-client";
import { ACCOUNT_SUSPENDED_MESSAGE } from "@pulseos/ui";

import { loadOrRegisterProfile, registrationFullName } from "./loadProfile";

const PROFILE: PatientProfile = {
  healthId: "PHI-IND-2026-7K3M99X",
  fullName: "Asha Rao",
  dateOfBirth: null,
  gender: null,
  createdAt: "2026-08-28T10:00:00Z",
};

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

function stubClient(getResults: StubResult[], postResults: StubResult[] = []) {
  const GET = vi.fn(() => Promise.resolve(getResults.shift()));
  const POST = vi.fn(() => Promise.resolve(postResults.shift()));
  return { client: { GET, POST } as unknown as PulseOSClient, GET, POST };
}

const IDENTITY = { displayName: "Asha Rao", email: "asha@example.test" };

test("already-registered user gets the profile without registering", async () => {
  const { client, POST } = stubClient([ok(PROFILE)]);
  const refresh = vi.fn(() => Promise.resolve());

  const result = await loadOrRegisterProfile(client, IDENTITY, refresh);

  expect(result).toEqual({ status: "ready", profile: PROFILE });
  expect(POST).not.toHaveBeenCalled();
  expect(refresh).not.toHaveBeenCalled();
});

test("first login registers transparently, refreshes the token, then retries", async () => {
  const { client, GET, POST } = stubClient([fail(403), ok(PROFILE)], [ok(PROFILE, 201)]);
  const refresh = vi.fn(() => Promise.resolve());

  const result = await loadOrRegisterProfile(client, IDENTITY, refresh);

  expect(result).toEqual({ status: "ready", profile: PROFILE });
  expect(POST).toHaveBeenCalledWith("/api/v1/patients/register", {
    body: { fullName: "Asha Rao" },
  });
  expect(refresh).toHaveBeenCalledOnce();
  expect(GET).toHaveBeenCalledTimes(2);
});

test("registration conflict (different role) surfaces the problem detail", async () => {
  const { client } = stubClient(
    [fail(403)],
    [fail(409, { detail: "Account is already registered with a different role." })],
  );

  const result = await loadOrRegisterProfile(
    client,
    IDENTITY,
    vi.fn(() => Promise.resolve()),
  );

  expect(result).toEqual({
    status: "error",
    message: "Account is already registered with a different role.",
  });
});

test("non-403 failures do not trigger registration", async () => {
  const { client, POST } = stubClient([fail(401, { detail: "Invalid authentication token." })]);

  const result = await loadOrRegisterProfile(
    client,
    IDENTITY,
    vi.fn(() => Promise.resolve()),
  );

  expect(result).toEqual({ status: "error", message: "Invalid authentication token." });
  expect(POST).not.toHaveBeenCalled();
});

test("still-403 after registration becomes an error, not a loop", async () => {
  const { client, GET } = stubClient([fail(403), fail(403)], [ok(PROFILE, 201)]);

  const result = await loadOrRegisterProfile(
    client,
    IDENTITY,
    vi.fn(() => Promise.resolve()),
  );

  expect(result.status).toBe("error");
  expect(GET).toHaveBeenCalledTimes(2); // no retry loop
});

test("registrationFullName falls back from display name to email to placeholder", () => {
  expect(registrationFullName({ displayName: "  Asha Rao ", email: null })).toBe("Asha Rao");
  expect(registrationFullName({ displayName: null, email: "asha.r@example.test" })).toBe("asha.r");
  expect(registrationFullName({ displayName: "  ", email: null })).toBe("PulseOS Patient");
  expect(registrationFullName({ displayName: "x".repeat(200), email: null })).toHaveLength(120);
});

test("a suspended account is reported and never registered", async () => {
  const { client, POST } = stubClient([fail(403, { detail: "Account is suspended." })]);
  const refresh = vi.fn(() => Promise.resolve());

  const result = await loadOrRegisterProfile(client, IDENTITY, refresh);

  expect(result).toEqual({ status: "error", message: ACCOUNT_SUSPENDED_MESSAGE });
  expect(POST).not.toHaveBeenCalled();
  expect(refresh).not.toHaveBeenCalled();
});
