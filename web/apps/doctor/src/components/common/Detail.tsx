// A labelled fact inside a <dl>: small muted label above its value.

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
