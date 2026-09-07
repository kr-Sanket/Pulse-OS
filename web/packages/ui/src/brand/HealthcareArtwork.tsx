// The left brand panel's visual, authored as an inline SVG.
//
// It is a component rather than an asset because the repository has no image pipeline and
// no committed artwork: there is no `public/` directory in any app, and the only images in
// the tree live under the gitignored `v0-reference/` (third-party marks we must not ship).
// Drawing it in SVG also keeps it on the design tokens — every stroke is `currentColor`, so
// the artwork inherits whatever the brand panel sets and cannot drift from the palette.
//
// Purely decorative: it carries no information the surrounding copy does not, so it is
// `aria-hidden` and unfocusable rather than given a label. Deliberately static — nothing
// here animates, so there is no reduced-motion case to answer.

export function HealthcareArtwork({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 400 340"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
    >
      {/* Concentric rings: depth behind the cards, nothing more. */}
      <g stroke="currentColor" strokeWidth="1.5">
        <circle cx="200" cy="170" r="156" opacity="0.10" />
        <circle cx="200" cy="170" r="118" opacity="0.14" />
      </g>

      {/* A record behind the record — the "same patient, many hospitals" idea, abstracted. */}
      <rect
        x="84"
        y="74"
        width="204"
        height="132"
        rx="18"
        fill="currentColor"
        opacity="0.10"
        transform="rotate(-7 186 140)"
      />

      {/* The foreground record card, with a pulse trace across it. */}
      <g transform="translate(104 92)">
        <rect width="216" height="140" rx="20" fill="currentColor" opacity="0.16" />
        <rect x="22" y="24" width="78" height="8" rx="4" fill="currentColor" opacity="0.38" />
        <rect x="22" y="41" width="48" height="8" rx="4" fill="currentColor" opacity="0.24" />
        <path
          d="M22 98h30l12-27 14 51 14-35 10 19h68"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.85"
        />
      </g>

      {/* Shield and heart: consent is the choke point, so protection is the closing note. */}
      <g transform="translate(272 190)">
        <path
          d="M34 2 64 13v26c0 17-14 29-30 34C18 68 4 56 4 39V13Z"
          fill="currentColor"
          fillOpacity="0.16"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <path
          d="M34 52c-9-7-18-13-18-21 0-6 5-10 10-10 4 0 7 2 8 5 1-3 4-5 8-5 5 0 10 4 10 10 0 8-9 14-18 21Z"
          fill="currentColor"
          opacity="0.9"
        />
      </g>

      {/* Subtle geometry, to keep the composition from ending abruptly. */}
      <g fill="currentColor">
        <circle cx="66" cy="252" r="6" opacity="0.30" />
        <circle cx="92" cy="272" r="4" opacity="0.20" />
        <circle cx="336" cy="96" r="5" opacity="0.24" />
      </g>
    </svg>
  );
}
