// Byte counts as a reader understands them.
//
// Shared across portals rather than owned by one feature: the patient portal sizes the
// documents in its own locker and the doctor portal sizes the ones a grant has made
// available, and a file that reads "2.4 MB" on one screen must not read "2458 KB" on the
// other. The same reasoning that moved date formatting and the category vocabulary here.

/** `1536` → "2 KB", `2_516_582` → "2.4 MB". Whole units below a megabyte — a tenth of a
 * kilobyte is noise — and one decimal above it, where the difference is worth reading. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kilobytes = bytes / 1024;
  if (kilobytes < 1024) {
    return `${Math.round(kilobytes)} KB`;
  }
  return `${(kilobytes / 1024).toFixed(1)} MB`;
}
