// The login presentation shared by all three PulseOS portals.
//
// The three login pages were near-identical hand-written copies (the doctor's and the
// hospital's differed only in two sentences; the patient's had never been moved onto the
// design system at all). This is the same hoist the shadcn primitives got, for the same
// reason: one implementation means the three surfaces cannot drift.
//
// Strictly presentational. It imports nothing from ../auth, holds no state and takes no
// callback — the sign-in action arrives as `children`, so every portal's page keeps its own
// auth guards and this file never learns that Firebase exists.
//
// What is shared here is the frame: background, split container, responsive collapse, brand
// panel, artwork, the "Welcome!" heading, and the error region (so `role="alert"` is
// declared once). What each portal supplies is its name and its one line of copy.

import type * as React from "react";

import { HeartPulse } from "lucide-react";

import { HealthcareArtwork } from "../brand/HealthcareArtwork";

/**
 * The class list for the sign-in control in the action slot.
 *
 * Exported rather than applied here because the button belongs to the page, which owns the
 * auth call — but its *appearance* is shared design, and three copies of this string would
 * be three chances to diverge.
 *
 * Two overrides, both deliberate:
 *
 *   • `h-11` (44px). The Button primitive's own sizes top out at 36px, below a comfortable
 *     touch target for the one control on the page.
 *   • the background. `bg-primary` under near-white text measures 3.99:1, short of WCAG AA
 *     for normal text — a token-level shortfall this file cannot fix without restyling
 *     every primary button in all three portals. Deepening it here takes the login CTA to
 *     5.6:1 and matches the brand panel beside it. The primitive and the tokens are
 *     untouched; see the report accompanying this slice.
 *
 * Both backgrounds carry `!`. Tailwind v4 orders arbitrary-value utilities *before* named
 * ones, so `bg-primary` from `buttonVariants` is emitted later and would otherwise win on
 * equal specificity — the override would compile and then do nothing. Verified against the
 * built stylesheet, not assumed.
 */
export const AUTH_ACTION_CLASS =
  "h-11 w-full justify-center rounded-xl bg-[color-mix(in_oklch,var(--primary),black_14%)]! " +
  "text-[15px] font-medium hover:bg-[color-mix(in_oklch,var(--primary),black_24%)]!";

/** The action label. Identical in every portal, so it lives here and not in a view.ts. */
export function signInActionLabel(busy: boolean): string {
  return busy ? "Signing in…" : "Continue with Google";
}

const WELCOME_HEADING = "Welcome!";

/** Brand-panel copy. Shared, and true of the product rather than of any one portal. */
const BRAND_TAGLINE =
  "One health identity, records that travel with the patient, and consent recorded at every step.";

export interface AuthShellProps {
  /** Which portal this is — "Patient portal", "Doctor portal", "Hospital portal". */
  portalName: string;
  /** The portal's one line under the heading: who should sign in, and with what. */
  subtitle: string;
  /** Overridable only for completeness; no portal overrides it, which is the point. */
  heading?: string;
  /** The already-sanitized message from `useSignIn`, or null. Never a raw provider error. */
  error?: string | null;
  /** The sign-in control. */
  children: React.ReactNode;
}

export function AuthShell({
  portalName,
  subtitle,
  heading = WELCOME_HEADING,
  error = null,
  children,
}: AuthShellProps) {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center bg-[radial-gradient(125%_125%_at_0%_0%,var(--primary-muted)_0%,var(--background)_46%,var(--secondary)_100%)] px-5 py-10 sm:px-6">
      {/* Card chrome starts at md. Below that the content sits straight on the page, which
          is what keeps a small screen from being a letterboxed desktop layout. */}
      <div className="md:ring-border/70 w-full max-w-5xl md:overflow-hidden md:rounded-3xl md:bg-card md:shadow-lg md:ring-1 lg:grid lg:grid-cols-2 lg:items-stretch">
        {/* Brand. A plain lockup on mobile, a tinted band at md, the full panel at lg. */}
        <section className="flex flex-col items-center gap-2 text-center md:flex-row md:items-center md:justify-between md:gap-4 md:bg-[linear-gradient(155deg,color-mix(in_oklch,var(--primary),black_12%)_0%,color-mix(in_oklch,var(--primary),black_30%)_100%)] md:px-8 md:py-5 md:text-left md:text-primary-foreground lg:flex-col lg:items-start lg:justify-between lg:gap-10 lg:px-10 lg:py-12">
          <div className="flex flex-col items-center gap-1 md:flex-row md:items-center md:gap-3 lg:flex-col lg:items-start lg:gap-2">
            <div className="flex items-center gap-2.5">
              <HeartPulse
                className="text-primary md:text-primary-foreground size-7"
                aria-hidden="true"
              />
              <span className="text-xl font-semibold tracking-tight">PulseOS</span>
            </div>
            <p className="text-muted-foreground md:text-primary-foreground/90 text-sm font-medium">
              {portalName}
            </p>
          </div>

          {/* `display: none` below lg: not painted, not laid out, and out of the
              accessibility tree. It does stay in the markup — about a kilobyte of inert
              SVG — which is the trade for keeping the breakpoint in CSS instead of adding
              a JS media-query hook for a decorative graphic. */}
          <HealthcareArtwork className="hidden w-full max-w-[22rem] lg:block" />

          <p className="text-primary-foreground/90 hidden text-sm leading-relaxed lg:block lg:max-w-[26rem]">
            {BRAND_TAGLINE}
          </p>
        </section>

        {/* Authentication. */}
        <section className="mt-9 w-full md:mt-0 md:bg-card md:px-8 md:py-10 lg:flex lg:flex-col lg:justify-center lg:px-14 lg:py-16">
          <div className="mx-auto w-full max-w-sm text-center">
            <h1 className="text-foreground text-2xl font-semibold tracking-tight sm:text-[28px]">
              {heading}
            </h1>
            <p className="text-muted-foreground mt-2.5 text-sm leading-relaxed">{subtitle}</p>

            <div className="mt-8">{children}</div>

            {error === null ? null : (
              <p role="alert" className="text-destructive mt-4 text-sm leading-relaxed">
                {error}
              </p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
