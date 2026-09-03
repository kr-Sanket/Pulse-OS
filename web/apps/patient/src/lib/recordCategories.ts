// The record-category controlled vocabulary (GET /api/v1/record-categories).
//
// Shared rather than owned by one feature: Records draws its filter chips and upload form
// from it, and Consent needs it to render the categories a request asks for as words
// instead of wire codes. One implementation, so the two can never disagree about what
// "DISCHARGE_SUMMARY" is called.

import type { components, PulseOSClient } from "@pulseos/api-client";

import { attempt, failure, type ApiResult } from "./apiResult";

export type RecordCategory = components["schemas"]["RecordCategoryResponse"];

export async function listCategories(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<RecordCategory[]>> {
  return attempt(async () => {
    const result = await client.GET("/api/v1/record-categories", { signal });
    if (result.data === undefined) {
      return failure(result.error, "Could not load record categories.");
    }
    return { status: "ready", data: result.data.items };
  });
}

/** code → display name, for rendering a stored code. Unknown codes render as themselves,
 * which is truthful: the server knows a category this build has never heard of. */
export function categoryLabels(categories: readonly RecordCategory[]): Map<string, string> {
  return new Map(categories.map((category) => [category.code, category.displayName]));
}

export function categoryLabel(labels: ReadonlyMap<string, string>, code: string): string {
  return labels.get(code) ?? code;
}
