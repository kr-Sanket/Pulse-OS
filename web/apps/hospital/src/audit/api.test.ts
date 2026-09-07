import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "@pulseos/api-client";

import { PAGE_SIZE, listHospitalAuditEvents } from "./api";

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
const PAGE = { items: [], nextCursor: null };

// -- query construction --------------------------------------------------------------

test("the first page is asked for with a limit and no cursor", () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  return listHospitalAuditEvents(client, SIGNAL).then(() => {
    expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me/audit-logs", {
      params: { query: { limit: PAGE_SIZE } },
      signal: SIGNAL,
    });
  });
});

test("a cursor is echoed back exactly as the API gave it", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  await listHospitalAuditEvents(client, SIGNAL, "opaque-cursor-value");

  expect(call).toHaveBeenCalledWith("/api/v1/hospitals/me/audit-logs", {
    params: { query: { limit: PAGE_SIZE, cursor: "opaque-cursor-value" } },
    signal: SIGNAL,
  });
});

test("no hospital parameter is ever sent — the scope is the caller's own", async () => {
  const { client, call } = stubClient({ data: PAGE, response: { status: 200 } });

  await listHospitalAuditEvents(client, SIGNAL);

  const query = (call.mock.calls[0] as unknown[])[1] as { params: { query: object } };
  expect(Object.keys(query.params.query)).toEqual(["limit"]);
});

test("the page size is smaller than the API cap, because this screen has a real pager", () => {
  expect(PAGE_SIZE).toBeLessThan(100);
});

// -- success mapping ---------------------------------------------------------------------

test("a successful response is returned unchanged", async () => {
  const page = {
    items: [
      {
        id: "evt-1",
        action: "RECORD_VIEWED",
        actorUserId: "u-1",
        actorRole: "HOSPITAL_ADMIN",
        actor: null,
        targetRecordId: "rec-1",
        occurredAt: "2026-09-04T09:30:00Z",
      },
    ],
    nextCursor: "next",
  };
  const { client } = stubClient({ data: page, response: { status: 200 } });

  expect(await listHospitalAuditEvents(client, SIGNAL)).toEqual({ status: "ready", data: page });
});

// -- error propagation ----------------------------------------------------------------------

test("each documented status maps to wording an administrator can act on", async () => {
  const cases: [number, string][] = [
    [401, "Your session has expired. Sign in again to see your audit history."],
    [403, "This account cannot view your hospital's audit history."],
    [404, "No hospital administrator profile is attached to this account."],
    [422, "That page of audit history could not be loaded. Reload to start again."],
  ];
  for (const [status, message] of cases) {
    const { client } = stubClient({ error: {}, response: { status } });

    expect(await listHospitalAuditEvents(client, SIGNAL)).toEqual({ status: "error", message });
  }
});

test("the API's own problem detail wins over the portal's wording", async () => {
  const { client } = stubClient({
    error: { detail: "Cursor is not valid for this listing." },
    response: { status: 422 },
  });

  expect(await listHospitalAuditEvents(client, SIGNAL)).toEqual({
    status: "error",
    message: "Cursor is not valid for this listing.",
  });
});

test("an unmapped status falls back rather than showing nothing", async () => {
  const { client } = stubClient({ error: {}, response: { status: 500 } });

  expect(await listHospitalAuditEvents(client, SIGNAL)).toEqual({
    status: "error",
    message: "Could not load your hospital's audit history.",
  });
});

test("a rejected fetch becomes an error result rather than throwing", async () => {
  const { client } = stubClient(new Error("offline"));

  expect((await listHospitalAuditEvents(client, SIGNAL)).status).toBe("error");
});
