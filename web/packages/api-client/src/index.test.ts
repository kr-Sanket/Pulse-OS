import { expect, test } from "vitest";

import { createPulseOSClient, problemDetail } from "./index";

function captureFetch(status = 200, body: unknown = { status: "ok" }) {
  const requests: Request[] = [];
  const fetchStub: typeof globalThis.fetch = (input) => {
    requests.push(input as Request);
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  };
  return { requests, fetchStub };
}

test("attaches the bearer token to every request", async () => {
  const { requests, fetchStub } = captureFetch();
  const client = createPulseOSClient({
    baseUrl: "http://api.test",
    getAccessToken: () => Promise.resolve("token-123"),
    fetch: fetchStub,
  });

  await client.GET("/health");

  expect(requests).toHaveLength(1);
  expect(requests[0]?.headers.get("Authorization")).toBe("Bearer token-123");
  expect(requests[0]?.url).toBe("http://api.test/health");
});

test("sends no Authorization header when unauthenticated", async () => {
  const { requests, fetchStub } = captureFetch();
  const client = createPulseOSClient({
    baseUrl: "http://api.test",
    getAccessToken: () => Promise.resolve(null),
    fetch: fetchStub,
  });

  await client.GET("/health");

  expect(requests[0]?.headers.get("Authorization")).toBeNull();
});

test("problemDetail reads RFC 7807 bodies and tolerates anything else", () => {
  expect(problemDetail({ detail: "Account is not provisioned for PulseOS." })).toBe(
    "Account is not provisioned for PulseOS.",
  );
  expect(problemDetail({ title: "Unauthorized" })).toBeUndefined();
  expect(problemDetail("nope")).toBeUndefined();
  expect(problemDetail(null)).toBeUndefined();
});
