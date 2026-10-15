import { expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";

import { PendingRequestCard } from "./PendingRequestCard";
import type { ConsentRequestView } from "@/consent/view";

const BASE_REQUEST: ConsentRequestView = {
  id: "req-1",
  hospital: "St. Jude Hospital",
  clinician: "Dr. Sarah Chen · Cardiology",
  purpose: "Follow-up consultation and medication review",
  categories: ["Lab Results", "Clinical Notes", "Prescriptions"],
  categoryCodes: ["LAB_RESULT", "CLINICAL_NOTE", "PRESCRIPTION"],
  requestedAgo: "10 minutes ago",
  requestedOn: "15 Oct 2026",
  expiresOn: "22 Oct 2026",
  bucket: "pending",
  statusLabel: "Pending",
  statusTone: "warning",
};

test("1. Multiple requested categories are displayed separately with codes and labels", () => {
  const onDecide = vi.fn();
  const html = renderToString(
    <PendingRequestCard request={BASE_REQUEST} busy={null} error={null} onDecide={onDecide} />,
  );

  expect(html).toContain("Requested Record Categories");
  expect(html).toContain("Lab Results");
  expect(html).toContain("LAB_RESULT");
  expect(html).toContain("Clinical Notes");
  expect(html).toContain("CLINICAL_NOTE");
  expect(html).toContain("Prescriptions");
  expect(html).toContain("PRESCRIPTION");
});

test("2. Available choices, consequences, and quick actions are clearly visible", () => {
  const onDecide = vi.fn();
  const html = renderToString(
    <PendingRequestCard request={BASE_REQUEST} busy={null} error={null} onDecide={onDecide} />,
  );

  // Quick actions
  expect(html).toContain("Approve all");
  expect(html).toContain("Decline all");

  // Consequence text
  expect(html).toContain(
    "Approved categories grant temporary read access until the request expires.",
  );
  expect(html).toContain("Declined categories remain private and cannot be viewed.");

  // Per-category buttons
  expect(html).toContain("Decision for Lab Results");
  expect(html).toContain("Decision for Clinical Notes");
  expect(html).toContain("Decision for Prescriptions");
});

test("3. An unselected or incomplete decision cannot be submitted (disabled submit button)", () => {
  const onDecide = vi.fn();
  const html = renderToString(
    <PendingRequestCard request={BASE_REQUEST} busy={null} error={null} onDecide={onDecide} />,
  );

  expect(html).toContain("Select a decision for each category");
  expect(html).toContain('disabled=""');
  expect(onDecide).not.toHaveBeenCalled();
});

test("4. In-flight busy state shows submitting indicator and disables actions", () => {
  const onDecide = vi.fn();
  const html = renderToString(
    <PendingRequestCard request={BASE_REQUEST} busy={true} error={null} onDecide={onDecide} />,
  );

  expect(html).toContain("Submitting decisions…");
  expect(html).toContain('disabled=""');
});

test("5. API error state is displayed prominently with role=alert", () => {
  const onDecide = vi.fn();
  const errorMessage = "This request has already been answered, or it has expired.";
  const html = renderToString(
    <PendingRequestCard
      request={BASE_REQUEST}
      busy={null}
      error={errorMessage}
      onDecide={onDecide}
    />,
  );

  expect(html).toContain('role="alert"');
  expect(html).toContain(errorMessage);
});

test("6. Partial success renders Access Granted badge and notice for already-approved categories", () => {
  const onDecide = vi.fn();
  const partial = {
    approvedCodes: ["LAB_RESULT"],
    failedCodes: ["PRESCRIPTION", "CLINICAL_NOTE"],
  };
  const errorMessage =
    "Approved categories (Lab Results) may already have access granted, while the remaining categories still need a decision: Network timeout";

  const html = renderToString(
    <PendingRequestCard
      request={BASE_REQUEST}
      busy={null}
      error={errorMessage}
      partial={partial}
      onDecide={onDecide}
    />,
  );

  // Partial notice banner
  expect(html).toContain("Partial Decision Notice");
  expect(html).toContain(
    "Approved categories may already have access granted on the server. Please select a decision for the remaining categories to complete your response.",
  );

  // Access Granted badge for the already approved category
  expect(html).toContain("Access Granted");
  expect(html).toContain("Approved on Server");

  // Error message explaining partial outcome
  expect(html).toContain("Approved categories (Lab Results) may already have access granted");

  // Decision buttons still available for remaining categories
  expect(html).toContain("Decision for Clinical Notes");
  expect(html).toContain("Decision for Prescriptions");
});

test("7. Hard reload scenario: partial state reconstructed from server grants renders partial notice and allows deciding remaining categories without error message", () => {
  const onDecide = vi.fn();
  // State reconstructed from server grants after a page reload (memory errors are null)
  const partial = {
    approvedCodes: ["LAB_RESULT"],
    failedCodes: ["CLINICAL_NOTE", "PRESCRIPTION"],
  };

  const html = renderToString(
    <PendingRequestCard
      request={BASE_REQUEST}
      busy={null}
      error={null}
      partial={partial}
      onDecide={onDecide}
    />,
  );

  // Partial notice banner is shown purely from authoritative server state
  expect(html).toContain("Partial Decision Notice");
  expect(html).toContain(
    "Approved categories may already have access granted on the server. Please select a decision for the remaining categories to complete your response.",
  );

  // Approved category shows Access Granted badge and Approved on Server
  expect(html).toContain("Access Granted");
  expect(html).toContain("Approved on Server");

  // Undecided categories have interactive controls
  expect(html).toContain("Decision for Clinical Notes");
  expect(html).toContain("Decision for Prescriptions");

  // Submit button prompts user to decide remaining categories
  expect(html).toContain("Select decision for remaining categories");
});
