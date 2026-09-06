import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { registerHospital } from "./api";

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
  hospitalName: "  Tata Main Hospital  ",
  hospitalAddress: "  Bistupur, Jamshedpur  ",
  adminFullName: "  Anita Rao  ",
};

test("the draft is trimmed before it is sent", async () => {
  const { client, call } = stubClient({
    data: { adminFullName: "Anita Rao" },
    response: { status: 201 },
  });

  await registerHospital(client, DRAFT);

  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/register", {
    body: {
      hospitalName: "Tata Main Hospital",
      hospitalAddress: "Bistupur, Jamshedpur",
      adminFullName: "Anita Rao",
    },
  });
});

test("a blank address is sent as null, not as an empty string", async () => {
  // The column is nullable; "" would record that the address *is* the empty string.
  const { client, call } = stubClient({ data: {}, response: { status: 201 } });

  await registerHospital(client, { ...DRAFT, hospitalAddress: "   " });

  expect(call).toHaveBeenCalledWith(
    "/api/v1/hospitals/register",
    expect.objectContaining({ body: expect.objectContaining({ hospitalAddress: null }) }),
  );
});

test("an idempotent repeat (200) is a success, exactly like a fresh 201", async () => {
  const profile = { adminFullName: "Anita Rao" };
  const { client } = stubClient({ data: profile, response: { status: 200 } });

  expect(await registerHospital(client, DRAFT)).toEqual({ status: "ready", data: profile });
});

test("a role conflict surfaces as an error the form can show", async () => {
  const { client } = stubClient({ error: {}, response: { status: 409 } });

  const result = await registerHospital(client, DRAFT);

  expect(result).toEqual({
    status: "error",
    message: "This account is already registered on PulseOS under a different role.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await registerHospital(client, DRAFT)).status).toBe("error");
});
