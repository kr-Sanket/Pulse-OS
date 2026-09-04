// A labelled fact inside a <dl>: small muted label above its value.
//
// Promoted from a local helper once a third page needed it (records → consent → grants).
// Takes children rather than a string so a value can be a set of badges as easily as text.
// className exists so a caller can make one entry span its grid — the profile page's
// address does that.

import type { ReactNode } from "react";

import { cn } from "@pulseos/ui";

export interface DetailProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export function Detail({ label, children, className }: DetailProps) {
  return (
    <div className={cn("space-y-1", className)}>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-foreground text-sm">{children}</dd>
    </div>
  );
}
