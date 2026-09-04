import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { registerDoctor } from "./api";

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

const DRAFT = {
  fullName: "  Dr Meera Sharma ",
  registrationNumber: " MCI-2019-44718 ",
  specialty: " Cardiology ",
  hospitalHid: " hid-0001 ",
};

test("registration trims every field and uppercases the hospital ID", async () => {
  const profile = { fullName: "Dr Meera Sharma", status: "PENDING" };
  const { client, call } = stubClient({ data: profile, response: { status: 201 } });

  const result = await registerDoctor(client, DRAFT);

  expect(result).toEqual({ status: "ready", data: profile });
  expect(call).toHaveBeenCalledWith("/api/v1/doctors/register", {
    body: {
      fullName: "Dr Meera Sharma",
      registrationNumber: "MCI-2019-44718",
      specialty: "Cardiology",
      hospitalHid: "HID-0001",
    },
  });
});

test("a blank specialty is sent as null, not as an empty string", async () => {
  const { client, call } = stubClient({ data: {}, response: { status: 201 } });

  await registerDoctor(client, { ...DRAFT, specialty: "   " });

  expect(call).toHaveBeenCalledWith("/api/v1/doctors/register", {
    body: {
      fullName: "Dr Meera Sharma",
      registrationNumber: "MCI-2019-44718",
      specialty: null,
      hospitalHid: "HID-0001",
    },
  });
});

test("a repeat registration is a success, because the API is idempotent", async () => {
  const existing = { fullName: "Dr Meera Sharma", status: "ACTIVE" };
  const { client } = stubClient({ data: existing, response: { status: 200 } });

  expect(await registerDoctor(client, DRAFT)).toEqual({ status: "ready", data: existing });
});

test("an account already registered under another role gets the API's own words", async () => {
  const { client } = stubClient({
    error: { detail: "Account is already registered with a different role." },
    response: { status: 409 },
  });

  expect(await registerDoctor(client, DRAFT)).toEqual({
    status: "error",
    message: "Account is already registered with a different role.",
  });
});

test("a conflict with no detail still explains both causes", async () => {
  const { client } = stubClient({ error: {}, response: { status: 409 } });

  expect(await registerDoctor(client, DRAFT)).toMatchObject({
    message: "This account is already registered, or that hospital cannot take registrations yet.",
  });
});

test("an unknown hospital ID points at the field that caused it", async () => {
  const { client } = stubClient({ error: {}, response: { status: 422 } });

  expect(await registerDoctor(client, DRAFT)).toMatchObject({
    message: "Check your details — that hospital ID may not exist.",
  });
});

test("a provider outage says nothing was saved", async () => {
  const { client } = stubClient({ error: {}, response: { status: 503 } });

  expect(await registerDoctor(client, DRAFT)).toMatchObject({
    message: "PulseOS could not complete your registration just now. Nothing was saved; try again.",
  });
});

test("a rejected fetch is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  expect((await registerDoctor(client, DRAFT)).status).toBe("error");
});
