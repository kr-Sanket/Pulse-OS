import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";

import { CitationBadge } from "./CitationBadge";

test("CitationBadge renders index and category code", () => {
  const html = renderToString(
    <CitationBadge
      citationIndex={1}
      recordId="00000000-0000-0000-0000-000000000001"
      categoryCode="LAB_REPORT"
    />,
  );

  expect(html).toContain("[1]");
  expect(html).toContain("LAB_REPORT");
  expect(html).toContain('data-citation-index="1"');
});

test("CitationBadge renders without category code", () => {
  const html = renderToString(
    <CitationBadge citationIndex={3} recordId="00000000-0000-0000-0000-000000000003" />,
  );

  expect(html).toContain("[3]");
  expect(html).toContain('data-citation-index="3"');
});

test("CitationBadge does not render record UUID in visible text", () => {
  const recordId = "secret-record-uuid-1234";
  const html = renderToString(
    <CitationBadge citationIndex={2} recordId={recordId} categoryCode="PRESCRIPTION" />,
  );

  // Verify record UUID does not appear in visible text
  const visibleText = html.replace(/<[^>]*>/g, "");
  expect(visibleText).not.toContain(recordId);
  expect(visibleText).toContain("2");
  expect(visibleText).toContain("PRESCRIPTION");
});

test("CitationBadge clicking invokes onClick with recordId", () => {
  const onClick = vi.fn();
  const badge = CitationBadge({
    citationIndex: 2,
    recordId: "rec-patient-123",
    categoryCode: "PRESCRIPTION",
    onClick,
  });

  const preventDefault = vi.fn();
  badge.props.onClick({ preventDefault });

  expect(preventDefault).toHaveBeenCalled();
  expect(onClick).toHaveBeenCalledWith("rec-patient-123");
});
