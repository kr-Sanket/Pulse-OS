import { expect, test, vi } from "vitest";

import type { PulseOSClient } from "./index";
import { AIClientError, generatePatientAnswer, generatePatientSelfAnswer } from "./ai";

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

  await expect(generatePatientAnswer(client, PATIENT_ID, "inappropriate query")).rejects.toThrow(
    AIClientError,
  );

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

test("generatePatientSelfAnswer sends query, signal, and optional maxTokens to /api/v1/ai/me/answer without path params", async () => {
  const mockResponse = {
    answer: "Your blood glucose is within normal range [1].",
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

  const res = await generatePatientSelfAnswer(client, "What is my blood sugar?", 1500, SIGNAL);

  expect(res).toEqual(mockResponse);
  expect(postCall).toHaveBeenCalledWith("/api/v1/ai/me/answer", {
    body: {
      query: "What is my blood sugar?",
      maxTokens: 1500,
    },
    signal: SIGNAL,
  });
});

test("generatePatientSelfAnswer accepts object params form and defaults maxTokens to 1000", async () => {
  const mockResponse = {
    answer:
      "The available medical records do not contain information regarding the requested topic.",
    citations: [],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "Review primary records before clinical decisions.",
  };

  const { client, postCall } = stubClient({
    data: mockResponse,
    response: { status: 200 },
  });

  const res = await generatePatientSelfAnswer(client, {
    query: "Explain my latest lab reports",
  });

  expect(res).toEqual(mockResponse);
  expect(postCall).toHaveBeenCalledWith("/api/v1/ai/me/answer", {
    body: {
      query: "Explain my latest lab reports",
      maxTokens: 1000,
    },
    signal: undefined,
  });
});

test("generatePatientSelfAnswer throws AIClientError with server RFC 7807 detail on 422", async () => {
  const { client } = stubClient({
    error: { detail: "AI answer generation was blocked by safety filters." },
    response: { status: 422 },
  });

  await expect(generatePatientSelfAnswer(client, { query: "inappropriate query" })).rejects.toThrow(
    AIClientError,
  );

  try {
    await generatePatientSelfAnswer(client, { query: "inappropriate query" });
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(422);
    expect(error.message).toBe("AI answer generation was blocked by safety filters.");
    expect(error.detail).toBe("AI answer generation was blocked by safety filters.");
  }
});

test("generatePatientSelfAnswer handles authentication errors 401 and 403", async () => {
  const { client: client401 } = stubClient({
    error: {},
    response: { status: 401 },
  });

  try {
    await generatePatientSelfAnswer(client401, "What are my medications?");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(401);
    expect(error.message).toBe("Your session has expired. Sign in again to continue.");
  }

  const { client: client403 } = stubClient({
    error: {},
    response: { status: 403 },
  });

  try {
    await generatePatientSelfAnswer(client403, "What are my medications?");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(403);
    expect(error.message).toBe("You do not have permission to generate AI clinical summaries.");
  }
});

test("generatePatientSelfAnswer handles missing patient profile 404", async () => {
  const { client: clientWithDetail } = stubClient({
    error: { detail: "Patient profile not found." },
    response: { status: 404 },
  });

  try {
    await generatePatientSelfAnswer(clientWithDetail, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(404);
    expect(error.message).toBe("Patient profile not found.");
    expect(error.detail).toBe("Patient profile not found.");
  }

  const { client: clientWithoutDetail } = stubClient({
    error: {},
    response: { status: 404 },
  });

  try {
    await generatePatientSelfAnswer(clientWithoutDetail, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(404);
    expect(error.message).toBe("Could not generate clinical answer.");
  }
});

test("generatePatientSelfAnswer handles upstream AI failures 429, 502, 503, 504", async () => {
  // 429 Rate limit
  const { client: client429 } = stubClient({
    error: { detail: "AI service rate limit exceeded. Please retry later." },
    response: { status: 429 },
  });
  try {
    await generatePatientSelfAnswer(client429, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(429);
    expect(error.message).toBe("AI service rate limit exceeded. Please retry later.");
  }

  // 502 Invalid response
  const { client: client502 } = stubClient({
    error: {},
    response: { status: 502 },
  });
  try {
    await generatePatientSelfAnswer(client502, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(502);
    expect(error.message).toContain("invalid response");
  }

  // 503 Service unavailable
  const { client: client503 } = stubClient({
    error: {},
    response: { status: 503 },
  });
  try {
    await generatePatientSelfAnswer(client503, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(503);
    expect(error.message).toContain("temporarily unavailable");
  }

  // 504 Timeout
  const { client: client504 } = stubClient({
    error: {},
    response: { status: 504 },
  });
  try {
    await generatePatientSelfAnswer(client504, "query");
  } catch (err) {
    const error = err as AIClientError;
    expect(error.status).toBe(504);
    expect(error.message).toContain("timed out");
  }
});

test("generatePatientSelfAnswer security: request never carries patientId, healthId, or firebaseUid", async () => {
  const { client, postCall } = stubClient({
    data: { answer: "Safe response", citations: [] },
    response: { status: 200 },
  });

  await generatePatientSelfAnswer(client, {
    query: "Summarize active conditions",
    maxTokens: 500,
  });

  expect(postCall).toHaveBeenCalledTimes(1);
  const callArgs = postCall.mock.calls[0] as unknown as [
    string,
    { body: Record<string, unknown>; params?: unknown },
  ];
  const [endpoint, options] = callArgs;

  expect(endpoint).toBe("/api/v1/ai/me/answer");
  expect(options.params).toBeUndefined();

  const bodyKeys = Object.keys(options.body).sort();
  expect(bodyKeys).toEqual(["maxTokens", "query"]);

  expect(options.body).not.toHaveProperty("patientId");
  expect(options.body).not.toHaveProperty("patient_id");
  expect(options.body).not.toHaveProperty("healthId");
  expect(options.body).not.toHaveProperty("firebaseUid");
});
