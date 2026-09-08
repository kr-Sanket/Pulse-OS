import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { updateProfile } from "./api";

const PROFILE = {
  healthId: "PHI-IND-2026-J0TA0DK",
  fullName: "Joaquin Rice",
  dateOfBirth: "1962-08-27",
  gender: "MALE",
  createdAt: "2026-09-07T18:34:01Z",
};

function stubClient(
  result: { data?: unknown; error?: unknown; response: { status: number } } | Error,
) {
  const call = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return { client: { PATCH: call } as unknown as PulseOSClient, call };
}

test("only the changed fields are sent, as the PATCH body", async () => {
  const { client, call } = stubClient({ data: PROFILE, response: { status: 200 } });

  const result = await updateProfile(client, { fullName: "Joaquin Rice" });

  expect(call).toHaveBeenCalledWith("/api/v1/patients/me", { body: { fullName: "Joaquin Rice" } });
  expect(result).toEqual({ status: "ready", data: PROFILE });
});

test("an explicit null is forwarded, because it means clear rather than omit", async () => {
  const { client, call } = stubClient({ data: PROFILE, response: { status: 200 } });

  await updateProfile(client, { dateOfBirth: null, gender: null });

  expect(call).toHaveBeenCalledWith("/api/v1/patients/me", {
    body: { dateOfBirth: null, gender: null },
  });
});

test("an RFC 7807 detail is preferred over any wording of ours", async () => {
  const { client } = stubClient({
    error: { detail: "fullName: must not be blank" },
    response: { status: 422 },
  });

  const result = await updateProfile(client, { fullName: "" });

  expect(result).toEqual({ status: "error", message: "fullName: must not be blank" });
});

test("a status without a detail falls back to wording that names the situation", async () => {
  const { client } = stubClient({ error: {}, response: { status: 403 } });

  const result = await updateProfile(client, { fullName: "x" });

  expect(result.status).toBe("error");
  expect(result.status === "error" && result.message).toContain("not allowed");
});

test("a rejected fetch is an error result, not a throw", async () => {
  const { client } = stubClient(new Error("network down"));

  const result = await updateProfile(client, { fullName: "x" });

  expect(result.status).toBe("error");
});
