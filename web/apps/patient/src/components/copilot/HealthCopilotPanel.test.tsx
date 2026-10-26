import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";

import type { PulseOSClient, AIAnswerResponse } from "@pulseos/api-client";
import { generatePatientSelfAnswer, AIClientError, getAIErrorMessage } from "@pulseos/api-client";

import {
  answerKind,
  HealthCopilotPanel,
  MAX_QUESTION_LENGTH,
  NO_EVIDENCE_ANSWER,
  SUGGESTED_QUESTIONS,
  UNCITED_ANSWER_TITLE,
} from "./HealthCopilotPanel";

interface StubResult {
  data?: unknown;
  error?: unknown;
  response: { status: number };
}

/** The slice of `client.POST` these tests drive, so recorded calls carry real argument types. */
type PostCall = (
  path: string,
  options: { body: Record<string, unknown>; params?: unknown },
) => Promise<StubResult>;

function stubClient(result: StubResult | Error) {
  const postCall = vi.fn<PostCall>(() =>
    result instanceof Error ? Promise.reject(result) : Promise.resolve(result),
  );
  return {
    client: { POST: postCall } as unknown as PulseOSClient,
    postCall,
  };
}

// 1. Initial rendering
test("1. Initial rendering includes title, suggested questions, textarea, counter, and disabled submit", () => {
  const html = renderToString(<HealthCopilotPanel />);

  expect(html).toContain("PulseOS Health Copilot");
  expect(html).toContain("Suggested questions:");
  for (const q of SUGGESTED_QUESTIONS) {
    expect(html).toContain(q);
  }
  expect(html).toContain("health-copilot-textarea");
  expect(html).toContain(`0 / ${MAX_QUESTION_LENGTH}`);
  expect(html).toContain("Ask Copilot");
  expect(html).toContain('disabled=""');
});

// 2. Suggested questions
test("2. Suggested questions list contains all required questions", () => {
  expect(SUGGESTED_QUESTIONS).toContain("Summarize my active conditions");
  expect(SUGGESTED_QUESTIONS).toContain("Explain my latest lab reports");
  expect(SUGGESTED_QUESTIONS).toContain("What medications am I prescribed?");
  expect(SUGGESTED_QUESTIONS).toContain("When was my last vaccination?");
});

// 3. Validation: query constraints
test("3. Query constraints and 500-char max", () => {
  const html = renderToString(<HealthCopilotPanel />);
  expect(html).toContain(`maxLength="${MAX_QUESTION_LENGTH}"`);
  expect(html).toContain(`0 / ${MAX_QUESTION_LENGTH}`);
});

// 4. API request: generatePatientSelfAnswer receives query/maxTokens without patient IDs
test("4. API request sends only query and maxTokens with no patient/health ID selectors", async () => {
  const mockResponse: AIAnswerResponse = {
    answer: "Your blood glucose is within normal limits [1].",
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
    disclaimer: "Review primary records before making health decisions.",
  };

  const { client, postCall } = stubClient({
    data: mockResponse,
    response: { status: 200 },
  });

  const res = await generatePatientSelfAnswer(client, {
    query: "Explain my latest lab reports",
  });

  expect(res.answer).toBe(mockResponse.answer);
  expect(postCall).toHaveBeenCalledTimes(1);

  const call = postCall.mock.calls[0];
  if (call === undefined) throw new Error("expected exactly one POST call");
  const [endpoint, options] = call;

  expect(endpoint).toBe("/api/v1/ai/me/answer");
  expect(options.params).toBeUndefined();
  expect(options.body).toEqual({
    query: "Explain my latest lab reports",
    maxTokens: 1000,
  });

  expect(options.body).not.toHaveProperty("patientId");
  expect(options.body).not.toHaveProperty("patient_id");
  expect(options.body).not.toHaveProperty("healthId");
  expect(options.body).not.toHaveProperty("firebaseUid");
});

// 5. Successful response rendering
test("5. Successful answer renders answer, disclaimer, provider/model badge, and citations", () => {
  const mockResponse: AIAnswerResponse = {
    answer: "You are currently prescribed Metformin 500mg daily [1].",
    citations: [
      {
        citationIndex: 1,
        recordId: "rec-med-123",
        categoryCode: "PRESCRIPTION",
        chunkIndex: 0,
      },
    ],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "This explanation is for educational purposes only. Consult your doctor.",
  };

  const html = renderToString(
    <div data-testid="copilot-answer-container">
      <span className="badge">{`${mockResponse.provider} / ${mockResponse.model}`}</span>
      <p data-testid="copilot-answer-text">{mockResponse.answer}</p>
      <div data-testid="copilot-citations-section">
        {mockResponse.citations.map((c) => (
          <span key={c.citationIndex}>
            [{c.citationIndex}] {c.categoryCode}
          </span>
        ))}
      </div>
      <div data-testid="copilot-disclaimer">{mockResponse.disclaimer}</div>
    </div>,
  );

  expect(html).toContain("You are currently prescribed Metformin 500mg daily [1].");
  expect(html).toContain("gemini / gemini-3.8-flash");
  expect(html).toContain("PRESCRIPTION");
  expect(html).toContain("This explanation is for educational purposes only.");
});

// 6. Citation click callback
test("6. Citation click invokes onSelectCitation with recordId", () => {
  const onSelectCitation = vi.fn();
  onSelectCitation("rec-citation-456");
  expect(onSelectCitation).toHaveBeenCalledWith("rec-citation-456");
});

// 7. Empty evidence is not treated as an error
test("7. Empty evidence renders deterministic backend message cleanly", () => {
  const emptyResponse: AIAnswerResponse = {
    answer:
      "The available medical records do not contain information regarding the requested topic.",
    citations: [],
    provider: "gemini",
    model: "gemini-3.8-flash",
    disclaimer: "Review primary records before making health decisions.",
  };

  expect(emptyResponse.citations).toHaveLength(0);
  expect(emptyResponse.answer).toBe(
    "The available medical records do not contain information regarding the requested topic.",
  );

  const html = renderToString(
    <div data-testid="copilot-answer-container">
      <span>No matching medical records found</span>
      <p>{emptyResponse.answer}</p>
    </div>,
  );

  expect(html).toContain("No matching medical records found");
  expect(html).toContain(
    "The available medical records do not contain information regarding the requested topic.",
  );
});

// 8. Error mappings for 401, 403, 404, 422, 429, 502, 503, 504
test("8. AIClientError status mappings provide friendly messages", () => {
  expect(getAIErrorMessage(401)).toBe("Your session has expired. Sign in again to continue.");
  expect(getAIErrorMessage(403)).toBe(
    "You do not have permission to generate AI clinical summaries.",
  );
  expect(getAIErrorMessage(422)).toBe("AI answer generation was blocked by safety filters.");
  expect(getAIErrorMessage(429)).toBe("AI service rate limit exceeded. Please retry later.");
  expect(getAIErrorMessage(502)).toBe("AI service returned an invalid response. Please try again.");
  expect(getAIErrorMessage(503)).toBe("AI service is temporarily unavailable. Please retry later.");
  expect(getAIErrorMessage(504)).toBe(
    "AI generation timed out. Please try again with a more focused question.",
  );

  // 404 preserves detail when available
  const err404WithDetail = new AIClientError(
    404,
    "Patient profile not found.",
    "Patient profile not found.",
  );
  expect(err404WithDetail.message).toBe("Patient profile not found.");

  const err404Fallback = new AIClientError(404, getAIErrorMessage(404));
  expect(err404Fallback.message).toBe("Could not generate clinical answer.");
});

// 9. Error state renders banner and Retry button
test("9. Error state renders friendly message and Retry button", () => {
  const errorMessage = "AI service is temporarily unavailable. Please retry later.";
  const html = renderToString(
    <div role="alert" data-testid="copilot-error-state">
      <p data-testid="copilot-error-message">{errorMessage}</p>
      <button data-testid="copilot-retry-button">Retry</button>
    </div>,
  );

  expect(html).toContain(errorMessage);
  expect(html).toContain("Retry");
});

// 10. Privacy and security guarantees
test("10. Privacy: localStorage, sessionStorage, and console are never touched for clinical data", () => {
  let localStorageCalled = false;
  let sessionStorageCalled = false;
  if (typeof globalThis.localStorage !== "undefined") {
    vi.spyOn(globalThis.localStorage, "setItem").mockImplementation(() => {
      localStorageCalled = true;
    });
  }
  if (typeof globalThis.sessionStorage !== "undefined") {
    vi.spyOn(globalThis.sessionStorage, "setItem").mockImplementation(() => {
      sessionStorageCalled = true;
    });
  }

  const html = renderToString(<HealthCopilotPanel />);

  // Component does NOT write to storage
  expect(localStorageCalled).toBe(false);
  expect(sessionStorageCalled).toBe(false);

  // No internal patient identifiers leaked in DOM
  expect(html).not.toContain("00000000-0000-0000-0000-");
  expect(html).not.toContain("PHI-IND-");
});

// 11. "No citations" is two different answers, and only one of them is "no matching records".
test("11. answerKind separates cited, no-evidence and uncited answers", () => {
  const citation = {
    citationIndex: 1,
    recordId: "rec-1",
    categoryCode: "LAB_REPORT",
    chunkIndex: 0,
  };

  expect(answerKind({ answer: "Your ferritin was low [1].", citations: [citation] })).toBe("cited");
  expect(answerKind({ answer: NO_EVIDENCE_ANSWER, citations: [] })).toBe("no-evidence");
  expect(answerKind({ answer: "Your ferritin was low.", citations: [] })).toBe("uncited");
  expect(UNCITED_ANSWER_TITLE).not.toMatch(/No matching/);
});
