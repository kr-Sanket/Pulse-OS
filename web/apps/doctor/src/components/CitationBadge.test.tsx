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
  expect(html).toContain('data-record-id="00000000-0000-0000-0000-000000000001"');
  expect(html).toContain('data-citation-index="1"');
});

test("CitationBadge renders without category code", () => {
  const html = renderToString(
    <CitationBadge citationIndex={3} recordId="00000000-0000-0000-0000-000000000003" />,
  );

  expect(html).toContain("[3]");
  expect(html).toContain('data-citation-index="3"');
});

test("CitationBadge handleClick calls onClick with recordId", () => {
  const onClick = vi.fn();
  const badge = CitationBadge({
    citationIndex: 2,
    recordId: "rec-test-123",
    categoryCode: "PRESCRIPTION",
    onClick,
  });

  // Call the button onClick directly
  badge.props.onClick({ preventDefault: vi.fn() });
  expect(onClick).toHaveBeenCalledWith("rec-test-123");
});
