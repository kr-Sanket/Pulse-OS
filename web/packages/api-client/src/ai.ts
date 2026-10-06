// AI answer generation API client (ADR-003, ADR-007).
//
// Typed adapter for POST /api/v1/ai/patients/{patient_id}/answer.
// Uses openapi-fetch and existing RFC 7807 problem detail extraction.

import type { components } from "./generated/schema";
import type { PulseOSClient } from "./index";
import { problemDetail } from "./index";

export type AIAnswerRequest = components["schemas"]["AIAnswerRequest"];
export type AIAnswerResponse = components["schemas"]["AIAnswerResponse"];
export type AICitation = components["schemas"]["AICitationResponse"];

export const AI_STATUS_FAILURES: Readonly<Record<number, string>> = {
  401: "Your session has expired. Sign in again to continue.",
  403: "You do not have permission to generate AI clinical summaries.",
  422: "AI answer generation was blocked by safety filters.",
  429: "AI service rate limit exceeded. Please retry later.",
  502: "AI service returned an invalid response. Please try again.",
  503: "AI service is temporarily unavailable. Please retry later.",
  504: "AI generation timed out. Please try again with a more focused question.",
};

export function getAIErrorMessage(
  status: number,
  fallback = "Could not generate clinical answer.",
): string {
  return AI_STATUS_FAILURES[status] ?? fallback;
}

export class AIClientError extends Error {
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "AIClientError";
    this.status = status;
    this.detail = detail;
  }
}

export interface GeneratePatientAnswerParams {
  patientId: string;
  query: string;
  maxTokens?: number;
  signal?: AbortSignal;
}

/**
 * Generate a synthesized clinical answer for a patient's records.
 *
 * Calls POST /api/v1/ai/patients/{patient_id}/answer using the provided client.
 * Returns the typed AIAnswerResponse containing answer, citations, and disclaimer.
 */
export async function generatePatientAnswer(
  client: PulseOSClient,
  patientId: string,
  query: string,
  maxTokens?: number,
  signal?: AbortSignal,
): Promise<AIAnswerResponse>;
export async function generatePatientAnswer(
  client: PulseOSClient,
  params: GeneratePatientAnswerParams,
): Promise<AIAnswerResponse>;
export async function generatePatientAnswer(
  client: PulseOSClient,
  patientIdOrParams: string | GeneratePatientAnswerParams,
  queryArg?: string,
  maxTokensArg?: number,
  signalArg?: AbortSignal,
): Promise<AIAnswerResponse> {
  const params: GeneratePatientAnswerParams =
    typeof patientIdOrParams === "string"
      ? {
          patientId: patientIdOrParams,
          query: queryArg ?? "",
          maxTokens: maxTokensArg,
          signal: signalArg,
        }
      : patientIdOrParams;

  const result = await client.POST("/api/v1/ai/patients/{patient_id}/answer", {
    params: {
      path: { patient_id: params.patientId },
    },
    body: {
      query: params.query,
      maxTokens: params.maxTokens ?? 1000,
    },
    signal: params.signal,
  });

  if (result.data !== undefined) {
    return result.data;
  }

  const status = result.response?.status ?? 500;
  const detail = problemDetail(result.error);
  const message = detail ?? getAIErrorMessage(status);
  throw new AIClientError(status, message, detail);
}

export interface GeneratePatientSelfAnswerParams {
  query: string;
  maxTokens?: number;
  signal?: AbortSignal;
}

/**
 * Generate a synthesized clinical answer for an authenticated patient's own records.
 *
 * Calls POST /api/v1/ai/me/answer using the provided client.
 * Identity is derived strictly from authentication; requires Role.PATIENT.
 * Returns the typed AIAnswerResponse containing answer, citations, and disclaimer.
 */
export async function generatePatientSelfAnswer(
  client: PulseOSClient,
  query: string,
  maxTokens?: number,
  signal?: AbortSignal,
): Promise<AIAnswerResponse>;
export async function generatePatientSelfAnswer(
  client: PulseOSClient,
  params: GeneratePatientSelfAnswerParams,
): Promise<AIAnswerResponse>;
export async function generatePatientSelfAnswer(
  client: PulseOSClient,
  queryOrParams: string | GeneratePatientSelfAnswerParams,
  maxTokensArg?: number,
  signalArg?: AbortSignal,
): Promise<AIAnswerResponse> {
  const params: GeneratePatientSelfAnswerParams =
    typeof queryOrParams === "string"
      ? {
          query: queryOrParams,
          maxTokens: maxTokensArg,
          signal: signalArg,
        }
      : queryOrParams;

  const result = await client.POST("/api/v1/ai/me/answer", {
    body: {
      query: params.query,
      maxTokens: params.maxTokens ?? 1000,
    },
    signal: params.signal,
  });

  if (result.data !== undefined) {
    return result.data;
  }

  const status = result.response?.status ?? 500;
  const detail = problemDetail(result.error);
  const message = detail ?? getAIErrorMessage(status);
  throw new AIClientError(status, message, detail);
}
