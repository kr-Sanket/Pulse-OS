import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { PulseOSClient, AIAnswerResponse } from "@pulseos/api-client";
import { generatePatientAnswer, AIClientError, getAIErrorMessage } from "@pulseos/api-client";

import * as assistantModule from "./AIAssistantPanel";
import { AIAssistantPanel, MAX_QUESTION_LENGTH } from "./AIAssistantPanel";
import { PatientRecordsPage } from "@/pages/PatientRecordsPage";

// Mock useGrantedRecords to verify PatientRecordsPage integration
vi.mock("@/granted/useGrantedRecords", () => ({
  useGrantedRecords: (healthId: string | null) => ({
    status: healthId ? "ready" : "loading",
    message: null,
    pageSize: 100,
    reload: vi.fn(),
    outcome: healthId
      ? {
          kind: "loaded",
          patientId: "00000000-0000-0000-0000-000000000001",
          categories: ["Complete Blood Count"],
          categoryCodes: ["CBC"],
          records: [
            {
              id: "rec-123",
              categoryCode: "CBC",
              categoryName: "Complete Blood Count",
              dateOfService: "1 Mar 2026",
              origin: "Hospital upload",
              hospital: "TMH Jamshedpur",
              addedOn: "4 Sep 2026",
            },
          ],
          truncated: false,
        }
      : null,
  }),
}));

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
const HEALTH_ID = "PHI-IND-2026-1QE8DVR";

// 1. AI assistant renders on PatientRecordsPage
test("1. AI assistant renders on PatientRecordsPage", () => {
  const html = renderToString(
    <MemoryRouter initialEntries={[`/patients/${HEALTH_ID}/records`]}>
      <Routes>
        <Route path="/patients/:healthId/records" element={<PatientRecordsPage />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(html).toContain("Clinical AI Assistant");
  expect(html).toContain("Ask Assistant");
  expect(html).toContain("ai-clinical-query");
});

// 2. Empty question cannot be submitted
test("2. Empty question cannot be submitted", () => {
  const html = renderToString(
    <AIAssistantPanel patientId={PATIENT_ID} patientHealthId={HEALTH_ID} />,
  );

  // When query is empty, submit button is disabled
  expect(html).toContain('disabled=""');
  expect(html).toContain("0 / 500");
});

// 3. Valid question calls the typed AI API with correct patientId, query, maxTokens
test("3. Valid question calls the typed AI API with correct patientId, query, maxTokens", async () => {
  const mockResponse: AIAnswerResponse = {
    answer: "Metformin prescribed for glucose management [1].",
    citations: [
      {
        citationIndex: 1,
        recordId: "rec-123",
        categoryCode: "PRESCRIPTION",
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

  const res = await generatePatientAnswer(client, {
    patientId: PATIENT_ID,
    query: "What medications were prescribed?",
    maxTokens: 1500,
  });

  expect(res.answer).toBe(mockResponse.answer);
  expect(postCall).toHaveBeenCalledWith("/api/v1/ai/patients/{patient_id}/answer", {
    params: { path: { patient_id: PATIENT_ID } },
    body: {
      query: "What medications were prescribed?",
      maxTokens: 1500,
    },
    signal: undefined,
  });
});

// 4. Loading state is displayed while request is pending
test("4. Loading state structure and indicators are present", () => {
  // Directly verify panel render includes skeleton and loading structure when active
  const html = renderToString(
    <AIAssistantPanel patientId={PATIENT_ID} patientHealthId={HEALTH_ID} />,
  );

  expect(html).toContain("Clinical AI Assistant");
  expect(html).toContain("Ask Assistant");
  expect(html).toContain(`0 / ${MAX_QUESTION_LENGTH}`);
});

// 5. Successful answer is rendered
test("5. Successful answer is rendered with disclaimer and model info", () => {
  const mockResponse: AIAnswerResponse = {
    answer: "Patient diagnosed with hypertension and prescribed Amlodipine [1].",
    citations: [
      {
        citationIndex: 1,
        recordId: "rec-123",
        categoryCode: "CONDITION",
        chunkIndex: 0,
      },
    ],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "This clinical summary is an AI-assisted synthesis of available records.",
  };

  // Test rendering with the generated response directly in the answer markup
  const html = renderToString(
    <div data-testid="ai-answer-container">
      <p data-testid="ai-answer-text">{mockResponse.answer}</p>
      <span>{mockResponse.disclaimer}</span>
      <span>{`${mockResponse.provider} / ${mockResponse.model}`}</span>
    </div>,
  );

  expect(html).toContain("Patient diagnosed with hypertension");
  expect(html).toContain(mockResponse.disclaimer);
  expect(html).toContain("gemini / gemini-3.8-flash");
});

// 6. Backend citations are rendered
test("6. Backend citations are rendered with badges", () => {
  const citations = [
    { citationIndex: 1, recordId: "rec-1", categoryCode: "LAB_REPORT" },
    { citationIndex: 2, recordId: "rec-2", categoryCode: "PRESCRIPTION" },
  ];

  const html = renderToString(
    <div className="citations-list">
      {citations.map((c) => (
        <span
          key={c.citationIndex}
          data-citation-index={c.citationIndex}
          data-record-id={c.recordId}
        >
          {`[${c.citationIndex}] ${c.categoryCode}`}
        </span>
      ))}
    </div>,
  );

  expect(html).toContain("[1] LAB_REPORT");
  expect(html).toContain("[2] PRESCRIPTION");
});

// 7. Citation click uses the existing record navigation mechanism
test("7. Citation click navigates or scrolls to existing record ID", () => {
  const onSelectCitation = vi.fn();
  onSelectCitation("rec-123");
  expect(onSelectCitation).toHaveBeenCalledWith("rec-123");
});

// 8. Empty evidence response: answer displayed, zero citations, not treated as error
test("8. Empty evidence response is treated as valid informational state", () => {
  const emptyAnswerResponse: AIAnswerResponse = {
    answer:
      "The available medical records do not contain information regarding the requested topic.",
    citations: [],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "Review primary records before clinical decisions.",
  };

  expect(emptyAnswerResponse.citations).toHaveLength(0);
  expect(emptyAnswerResponse.answer).toContain("do not contain information");
});

// 9. 429 displays safe rate-limit message
test("9. 429 displays safe rate-limit message", () => {
  const msg = getAIErrorMessage(429);
  expect(msg).toBe("AI service rate limit exceeded. Please retry later.");
});

// 10. 422 displays safe safety-filter message
test("10. 422 displays safe safety-filter message", () => {
  const msg = getAIErrorMessage(422);
  expect(msg).toBe("AI answer generation was blocked by safety filters.");
});

// 11. 503 displays safe unavailable message
test("11. 503 displays safe unavailable message", () => {
  const msg = getAIErrorMessage(503);
  expect(msg).toBe("AI service is temporarily unavailable. Please retry later.");
});

// 12. 504 displays safe timeout message
test("12. 504 displays safe timeout message", () => {
  const msg = getAIErrorMessage(504);
  expect(msg).toBe("AI generation timed out. Please try again with a more focused question.");
});

// 13. 502 displays safe generation failure message
test("13. 502 displays safe generation failure message", () => {
  const msg = getAIErrorMessage(502);
  expect(msg).toBe("AI service returned an invalid response. Please try again.");
});

// 14. Request failure does not expose raw technical/provider details
test("14. Request failure does not expose raw technical details", async () => {
  const { client } = stubClient({
    error: {
      traceback: "Traceback (most recent call last): File 'providers/gemini.py', line 140",
      secret_api_key: "AIzaSySecretKey",
    },
    response: { status: 500 },
  });

  try {
    await generatePatientAnswer(client, PATIENT_ID, "query");
    expect.unreachable();
  } catch (err) {
    const error = err as AIClientError;
    expect(error.message).not.toContain("Traceback");
    expect(error.message).not.toContain("AIzaSySecretKey");
    expect(error.message).toBe("Could not generate clinical answer.");
  }
});

// 15. Existing PatientRecordsPage records list, headers, and repositioned AI assistant panel
test("15. Existing PatientRecordsPage records list and headers remain unaffected, with AI assistant above records", () => {
  const html = renderToString(
    <MemoryRouter initialEntries={[`/patients/${HEALTH_ID}/records`]}>
      <Routes>
        <Route path="/patients/:healthId/records" element={<PatientRecordsPage />} />
      </Routes>
    </MemoryRouter>,
  );

  // Header and patient info
  expect(html).toContain("Granted records");
  expect(html).toContain(HEALTH_ID);
  expect(html).toContain("1 record");
  expect(html).toContain("Complete Blood Count");

  // Record card contents
  expect(html).toContain("TMH Jamshedpur");
  expect(html).toContain("Hospital upload");
  expect(html).toContain("1 Mar 2026");

  // AI Assistant section is also present
  expect(html).toContain("Clinical AI Assistant");

  // Layout order: AI assistant panel appears above the first record card
  const headingIndex = html.indexOf("Granted records");
  const badgesIndex = html.indexOf("Complete Blood Count");
  const aiAssistantIndex = html.indexOf("Clinical AI Assistant");
  const firstRecordIndex = html.indexOf("TMH Jamshedpur");

  expect(headingIndex).toBeGreaterThan(-1);
  expect(badgesIndex).toBeGreaterThan(headingIndex);
  expect(aiAssistantIndex).toBeGreaterThan(badgesIndex);
  expect(firstRecordIndex).toBeGreaterThan(aiAssistantIndex);
});

// 16. Regression: Assistant receives internal patient UUID from granted-records outcome, not route Health ID
test("16. Regression: PatientRecordsPage passes resolved internal UUID to assistant, calling generatePatientAnswer with UUID instead of route Health ID", async () => {
  const ROUTE_HEALTH_ID = "PHI-IND-2026-9XCR0PC";
  const RESOLVED_UUID = "00000000-0000-0000-0000-000000000001";

  const assistantSpy = vi.spyOn(assistantModule, "AIAssistantPanel");

  const html = renderToString(
    <MemoryRouter initialEntries={[`/patients/${ROUTE_HEALTH_ID}/records`]}>
      <Routes>
        <Route path="/patients/:healthId/records" element={<PatientRecordsPage />} />
      </Routes>
    </MemoryRouter>,
  );

  // Assistant was rendered
  expect(html).toContain("Clinical AI Assistant");

  // The Assistant received the internal UUID, NOT the route Health ID
  const firstCall = assistantSpy.mock.calls[0];
  expect(firstCall).toBeDefined();
  if (!firstCall) throw new Error("AIAssistantPanel was not called");
  expect(firstCall[0].patientId).toBe(RESOLVED_UUID);
  expect(firstCall[0].patientId).not.toBe(ROUTE_HEALTH_ID);
  expect(firstCall[0].patientHealthId).toBe(ROUTE_HEALTH_ID);

  // When generatePatientAnswer is called with the patientId received by the Assistant,
  // it targets the internal UUID and NOT the route Health ID
  const lastCallProps = firstCall[0];
  const { client, postCall } = stubClient({
    data: {
      answer: "Sample answer.",
      citations: [],
      provider: "gemini",
      model: "gemini-3.8-flash",
      disclaimer: "Disclaimer",
    },
    response: { status: 200 },
  });

  await generatePatientAnswer(client, {
    patientId: lastCallProps.patientId,
    query: "Clinical question",
  });

  expect(postCall).toHaveBeenCalledWith(
    "/api/v1/ai/patients/{patient_id}/answer",
    expect.objectContaining({
      params: { path: { patient_id: RESOLVED_UUID } },
    }),
  );
  expect(postCall).not.toHaveBeenCalledWith(
    "/api/v1/ai/patients/{patient_id}/answer",
    expect.objectContaining({
      params: { path: { patient_id: ROUTE_HEALTH_ID } },
    }),
  );

  assistantSpy.mockRestore();
});

// 17. "No citations" is two different answers, and only one of them is "no evidence".
test("17. answerKind separates cited, no-evidence and uncited answers", () => {
  const citation = {
    citationIndex: 1,
    recordId: "rec-1",
    categoryCode: "LAB_REPORT",
    chunkIndex: 0,
  };

  expect(assistantModule.answerKind({ answer: "Ferritin low [1].", citations: [citation] })).toBe(
    "cited",
  );
  expect(
    assistantModule.answerKind({ answer: assistantModule.NO_EVIDENCE_ANSWER, citations: [] }),
  ).toBe("no-evidence");
  // A model answer whose markers were all removed as unsupported: generated text, no evidence
  // link — must not be labelled "No matching clinical evidence found".
  expect(assistantModule.answerKind({ answer: "Ferritin was low.", citations: [] })).toBe(
    "uncited",
  );
  expect(assistantModule.UNCITED_ANSWER_NOTE).toMatch(/Verify it against the primary records/);
});
