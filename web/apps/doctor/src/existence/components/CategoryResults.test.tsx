import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";

import type { SearchOutcome } from "@/existence/view";
import { CategoryResults, type CategorySelection } from "./CategoryResults";

const SAMPLE_OUTCOME: SearchOutcome = {
  kind: "found",
  healthId: "PHI-IND-2026-1QE8DVR",
  categories: [
    { code: "CBC", displayName: "Complete Blood Count" },
    { code: "MRI", displayName: "MRI Scan" },
    { code: "ALLERGY", displayName: "Allergy Records" },
  ],
};

function createSelection(overrides: Partial<CategorySelection> = {}): CategorySelection {
  return {
    selected: new Set(),
    grantedCodes: new Set(),
    onToggle: vi.fn(),
    onClear: vi.fn(),
    onRequestAccess: vi.fn(),
    canRequest: false,
    ...overrides,
  };
}

function getCheckboxElement(html: string, code: string): string {
  const match = html.match(new RegExp(`<button[^>]*id="category-${code}"[^>]*>`));
  return match ? match[0] : "";
}

// 1. Already-granted category: checkbox disabled and "Access granted" displayed.
test("1. Already-granted category: checkbox is disabled and '✓ Access granted' is displayed", () => {
  const selection = createSelection({
    grantedCodes: new Set(["CBC"]),
  });

  const html = renderToString(<CategoryResults outcome={SAMPLE_OUTCOME} selection={selection} />);

  // Category name and subtle teal/green '✓ Access granted' badge are displayed
  expect(html).toContain("Complete Blood Count");
  expect(html).toContain("✓ Access granted");

  // Check that the CBC checkbox element has disabled attributes
  const cbcCheckbox = getCheckboxElement(html, "CBC");
  expect(cbcCheckbox).not.toBe("");
  expect(cbcCheckbox).toContain('disabled=""');
  expect(cbcCheckbox).toContain('data-disabled=""');

  // Row has clear disabled visual state
  expect(html).toContain("cursor-default text-muted-foreground");
});

// 2. Category without access: checkbox remains selectable.
test("2. Category without access: checkbox remains enabled and selectable", () => {
  const selection = createSelection({
    grantedCodes: new Set(), // No granted categories
  });

  const html = renderToString(<CategoryResults outcome={SAMPLE_OUTCOME} selection={selection} />);

  // Badge is NOT displayed
  expect(html).not.toContain("✓ Access granted");

  // All category checkboxes are enabled (no disabled attribute)
  for (const cat of SAMPLE_OUTCOME.categories) {
    const checkbox = getCheckboxElement(html, cat.code);
    expect(checkbox).not.toBe("");
    expect(checkbox).not.toContain('disabled=""');
    expect(checkbox).not.toContain('data-disabled=""');
  }

  // Row styling has hover effect and cursor pointer
  expect(html).toContain("cursor-pointer hover:bg-accent/40");
});

// 3. Partial access: only granted categories are disabled.
test("3. Partial access: only granted categories are disabled, others remain selectable", () => {
  const selection = createSelection({
    grantedCodes: new Set(["ALLERGY"]),
    selected: new Set(["MRI"]),
    canRequest: true,
  });

  const html = renderToString(<CategoryResults outcome={SAMPLE_OUTCOME} selection={selection} />);

  // ALLERGY is granted -> disabled with badge
  const allergyCheckbox = getCheckboxElement(html, "ALLERGY");
  expect(allergyCheckbox).toContain('disabled=""');
  expect(allergyCheckbox).toContain('data-disabled=""');
  expect(html).toContain("✓ Access granted");

  // CBC and MRI are NOT granted -> enabled, without badge
  const cbcCheckbox = getCheckboxElement(html, "CBC");
  expect(cbcCheckbox).not.toContain('disabled=""');
  expect(cbcCheckbox).not.toContain('data-disabled=""');

  const mriCheckbox = getCheckboxElement(html, "MRI");
  expect(mriCheckbox).not.toContain('disabled=""');
  expect(mriCheckbox).not.toContain('data-disabled=""');

  // MRI is selected and checked
  expect(mriCheckbox).toContain('data-state="checked"');
});

// 4. Revoked/inactive access: category becomes selectable again.
test("4. Revoked/inactive access: category becomes selectable again when no longer in grantedCodes", () => {
  // Phase 1: Access is active
  const activeSelection = createSelection({
    grantedCodes: new Set(["CBC"]),
  });
  const activeHtml = renderToString(
    <CategoryResults outcome={SAMPLE_OUTCOME} selection={activeSelection} />,
  );
  expect(getCheckboxElement(activeHtml, "CBC")).toContain('disabled=""');
  expect(activeHtml).toContain("✓ Access granted");

  // Phase 2: Access revoked / expired -> grantedCodes is now empty (permission refreshed)
  const revokedSelection = createSelection({
    grantedCodes: new Set(),
  });
  const revokedHtml = renderToString(
    <CategoryResults outcome={SAMPLE_OUTCOME} selection={revokedSelection} />,
  );
  expect(getCheckboxElement(revokedHtml, "CBC")).not.toContain('disabled=""');
  expect(revokedHtml).not.toContain("✓ Access granted");
});

// 5. Existing access-request behavior remains unchanged for selectable categories.
test("5. Existing access-request behavior remains unchanged for selectable categories", () => {
  const onToggle = vi.fn();
  const onClear = vi.fn();
  const onRequestAccess = vi.fn();

  const selection = createSelection({
    grantedCodes: new Set(["CBC"]),
    selected: new Set(["MRI"]),
    canRequest: true,
    onToggle,
    onClear,
    onRequestAccess,
  });

  const html = renderToString(<CategoryResults outcome={SAMPLE_OUTCOME} selection={selection} />);

  // Request Access button is enabled and clickable
  expect(html).toContain("Request Access");
  expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>[^<]*Request Access/);

  // Clear selection button is rendered
  expect(html).toContain("Clear selection");

  // Summary counter is correct
  expect(html).toContain("1 of 3 selected.");
});
