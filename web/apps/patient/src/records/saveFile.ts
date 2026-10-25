// Saving a Blob the browser already holds as a named download.
//
// The one DOM-touching step of the FHIR export, kept apart from records/api.ts so that
// module stays unit-testable without a DOM. The object URL is revoked only after a delay:
// some browsers (older Safari and Firefox) start reading the URL after `click()` returns,
// and an immediate revoke can cancel the download.

/** Long enough for any browser to have started the download; short enough not to hoard. */
export const REVOKE_DELAY_MS = 30_000;

export function saveBlob(blob: Blob, filename: string, revokeDelayMs = REVOKE_DELAY_MS): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  link.style.display = "none";
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), revokeDelayMs);
  }
}
