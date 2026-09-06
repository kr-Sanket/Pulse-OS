// The download state machine, as pure decisions.
//
// The transitions live in @pulseos/ui as functions precisely so they can be tested without a
// DOM: the project's web tests are pure logic (no Testing Library, no jsdom), and the two
// rules worth pinning here — never ask twice, never claim nothing happened — are the two
// with an audit consequence behind them.

import { expect, test } from "vitest";

import {
  canStartDownload,
  downloadOutcome,
  DOWNLOAD_IDLE,
  POPUP_BLOCKED,
  type DownloadState,
} from "@pulseos/ui";

const PREPARING: DownloadState = { kind: "preparing" };
const FAILED: DownloadState = { kind: "failed", message: "Could not prepare the download." };

test("a download starts from idle", () => {
  expect(canStartDownload(DOWNLOAD_IDLE)).toBe(true);
});

test("a second click is refused while a link is being prepared", () => {
  // The server records a download the moment it issues a link, so two clicks would put two
  // entries on the patient's audit trail for one intention.
  expect(canStartDownload(PREPARING)).toBe(false);
});

test("a failed download can be retried", () => {
  expect(canStartDownload(FAILED)).toBe(true);
});

test("an opened window returns the button to idle", () => {
  expect(downloadOutcome(true)).toEqual(DOWNLOAD_IDLE);
});

test("a blocked pop-up fails with wording that does not deny the download happened", () => {
  const outcome = downloadOutcome(false);

  expect(outcome).toEqual({ kind: "failed", message: POPUP_BLOCKED });
  expect(POPUP_BLOCKED).toContain("blocked the download window");
  expect(POPUP_BLOCKED).toContain("Allow pop-ups");
  // The link was issued and the download is already audited — the message must not say
  // "nothing was downloaded".
  expect(POPUP_BLOCKED).not.toContain("Nothing was downloaded");
});

test("a blocked pop-up is retryable, so the administrator is not stuck", () => {
  expect(canStartDownload(downloadOutcome(false))).toBe(true);
});
