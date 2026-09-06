// The download-a-file interaction, as every portal performs it.
//
// Both portals that can take a record's file do the same three things: ask the API for a
// short-lived presigned URL, open it, and report what went wrong beside the button. The
// state machine is shared because the *audit* consequence is shared — the server records a
// download the moment it issues the link, so a second click is a second entry on the
// patient's trail for one intention, and every caller must guard against it identically.

/** What a Download button is doing. `preparing` is what stops a second click from asking
 * the server for a second link — and from writing a second download to the patient's trail
 * for one intention. */
export type DownloadState =
  { kind: "idle" } | { kind: "preparing" } | { kind: "failed"; message: string };

export const DOWNLOAD_IDLE: DownloadState = { kind: "idle" };

/** Shown when the link was issued but the browser refused to follow it. The download has
 * already been audited at this point, so the message must not suggest nothing happened. */
export const POPUP_BLOCKED =
  "Your browser blocked the download window. Allow pop-ups for PulseOS and try again.";

/**
 * Whether a click should start a download.
 *
 * False while one is already being prepared. This is the duplicate-click guard, and it is a
 * function rather than a `disabled` attribute because the button's disabled state only
 * settles on the next render — two fast clicks can both pass it. The server records a
 * download the moment it issues a link, so a slip here writes a second entry on the
 * patient's audit trail for one intention.
 */
export function canStartDownload(state: DownloadState): boolean {
  return state.kind !== "preparing";
}

/**
 * What the button becomes once the browser has been asked to open the link.
 *
 * `opened` false means the pop-up was blocked. The link was still issued and the download is
 * already on the patient's trail, so the wording must not suggest nothing happened.
 */
export function downloadOutcome(opened: boolean): DownloadState {
  return opened ? DOWNLOAD_IDLE : { kind: "failed", message: POPUP_BLOCKED };
}
