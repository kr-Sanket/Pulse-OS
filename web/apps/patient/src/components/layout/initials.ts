// Initials for an avatar fallback. Used by the sidebar footer and the profile summary —
// the two places the signed-in user's identity is shown.

/** Up to two initials from a display name, else the email's first letter. */
export function initialsFor(displayName: string | null, email: string | null): string {
  const fromName = (displayName ?? "")
    .split(/\s+/)
    .filter((part) => part.length > 0)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
  if (fromName.length > 0) {
    return fromName;
  }
  const firstLetter = (email ?? "").charAt(0).toUpperCase();
  return firstLetter.length > 0 ? firstLetter : "?";
}
