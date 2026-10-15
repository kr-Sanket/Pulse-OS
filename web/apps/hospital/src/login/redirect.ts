// Safe internal path resolution for login redirects.
//
// Prevents open redirects by verifying that destination paths are internal, relative
// paths starting with a single '/' and containing no scheme colons, backslashes,
// protocol-relative '//', or loops back to /login.

export function getSafeRedirectPath(from: unknown, fallback = "/"): string {
  let candidate: string | undefined;

  if (typeof from === "string") {
    candidate = from;
  } else if (typeof from === "object" && from !== null && "pathname" in from) {
    const loc = from as { pathname?: unknown; search?: unknown; hash?: unknown };
    if (typeof loc.pathname === "string") {
      const search = typeof loc.search === "string" ? loc.search : "";
      const hash = typeof loc.hash === "string" ? loc.hash : "";
      candidate = `${loc.pathname}${search}${hash}`;
    }
  }

  if (!candidate) {
    return fallback;
  }

  const trimmed = candidate.trim();

  // Must begin with a single slash, not a double slash or protocol-relative
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.startsWith("/\\")) {
    return fallback;
  }

  // Reject scheme/protocol colons or backslashes
  if (trimmed.includes("\\") || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmed)) {
    return fallback;
  }

  // Reject looping back to /login
  if (trimmed === "/login" || trimmed.startsWith("/login?")) {
    return fallback;
  }

  return trimmed;
}
