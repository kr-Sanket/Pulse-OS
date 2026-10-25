// Saving a Blob the browser already holds as a named download.
//
// The one DOM-touching step of the FHIR export, kept apart from records/api.ts so that
// module stays unit-testable without a DOM. The object URL is revoked as soon as the click
// has been dispatched: the browser has taken its own reference by then.

export function saveBlob(blob: Blob, filename: string): void {
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
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
