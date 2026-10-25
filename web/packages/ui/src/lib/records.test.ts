import { expect, test } from "vitest";

import { aiIndexingNote, processingLabel } from "./records";

test("the AI note never claims images or text-less PDFs are searchable", () => {
  expect(aiIndexingNote("image/png", "UPLOADED")).toMatch(/Not searchable by AI.*OCR/);
  expect(aiIndexingNote("image/jpeg", "INDEXED")).toMatch(/Not searchable by AI/);
  expect(aiIndexingNote("application/pdf", "FAILED")).toMatch(/no readable text/);
  expect(aiIndexingNote("application/pdf", "UPLOADED")).toBe("Not yet indexed for AI search.");
  expect(aiIndexingNote("application/pdf", "INDEXED")).toMatch(/only within consent you grant/);
  expect(aiIndexingNote("application/fhir+json", "UPLOADED")).toBeNull();
});

test("processing labels describe AI indexing, not an unbuilt OCR pipeline", () => {
  expect(processingLabel("INDEXED")).toBe("Indexed for AI search");
  expect(processingLabel("FAILED")).toBe("Not indexed — no readable text");
  expect(processingLabel("UPLOADED")).toBe("Stored");
});
