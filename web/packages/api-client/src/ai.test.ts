import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "./index";
import { AIClientError, generatePatientAnswer } from "./ai";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

function stubClient(result: StubResult | Error) {
  const postCall = vi.fn(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return {
    client: { POST: postCall } as unknown as PulseOSClient,
    postCall,
  };
}

const PATIENT_ID = "00000000-0000-0000-0000-000000000001";
const SIGNAL = new AbortController().signal;

test("generatePatientAnswer sends query, path, and optional maxTokens", async () => {
  const mockResponse = {
    answer: "Blood pressure is controlled [1].",
    citations: [
      {
        citationIndex: 1,
        recordId: "00000000-0000-0000-0000-000000000002",
        categoryCode: "LAB_REPORT",
        chunkIndex: 0,
      },
    ],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "Review primary records before clinical decisions.",
  };

  const { client, postCall } = stubClient({
    data: mockResponse,
    response: { status: 200 },
  });

  const res = await generatePatientAnswer(client, PATIENT_ID, "What is the BP?", 1500, SIGNAL);

  expect(res).toEqual(mockResponse);
  expect(postCall).toHaveBeenCalledWith("/api/v1/ai/patients/{patient_id}/answer", {
    params: {
      path: { patient_id: PATIENT_ID },
    },
    body: {
      query: "What is the BP?",
      maxTokens: 1500,
    },
    signal: SIGNAL,
  });
});

test("generatePatientAnswer accepts object params form", async () => {
  const mockResponse = {
    answer: "No relevant findings.",
    citations: [],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "Disclaimer text",
  };

  const { client, postCall } = stubClient({
    data: mockResponse,
    response: { status: 200 },
  });

  const res = await generatePatientAnswer(client, {
    patientId: PATIENT_ID,
    query: "Any diabetes records?",
  });

  expect(res).toEqual(mockResponse);
  expect(postCall).toHaveBeenCalledWith("/api/v1/ai/patients/{patient_id}/answer", {
    params: {
      path: { patient_id: PATIENT_ID },
    },
    body: {
      query: "Any diabetes records?",
      maxTokens: 1000,
    },
    signal: undefined,
  });
});

test("generatePatientAnswer throws AIClientError with server RFC 7807 detail on 422", async () => {
  const { client } = stubClient({
    error: { detail: "AI answer generation was blocked by safety filters." },
    response: { status: 422 },
  });

  await expect(
    generatePatientAnswer(client, PATIENT_ID, "inappropriate query"),
  ).rejects.toThrow(AIClientError);

  try {
    await generatePatientAnswer(client, PATIENT_ID, "inappropriate query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(422);
    expect(error.message).toBe("AI answer generation was blocked by safety filters.");
  }
});

test("generatePatientAnswer handles rate limit 429", async () => {
  const { client } = stubClient({
    error: { detail: "AI service rate limit exceeded. Please retry later." },
    response: { status: 429 },
  });

  try {
    await generatePatientAnswer(client, PATIENT_ID, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(429);
    expect(error.message).toBe("AI service rate limit exceeded. Please retry later.");
  }
});

test("generatePatientAnswer handles timeout 504", async () => {
  const { client } = stubClient({
    error: {},
    response: { status: 504 },
  });

  try {
    await generatePatientAnswer(client, PATIENT_ID, "slow query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(504);
    expect(error.message).toContain("timed out");
  }
});

test("generatePatientAnswer handles service unavailable 503", async () => {
  const { client } = stubClient({
    error: {},
    response: { status: 503 },
  });

  try {
    await generatePatientAnswer(client, PATIENT_ID, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(503);
    expect(error.message).toContain("temporarily unavailable");
  }
});

test("generatePatientAnswer handles generation failure 502", async () => {
  const { client } = stubClient({
    error: {},
    response: { status: 502 },
  });

  try {
    await generatePatientAnswer(client, PATIENT_ID, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(502);
    expect(error.message).toContain("invalid response");
  }
});
