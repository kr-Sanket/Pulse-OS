// A Badge with a leading tone dot — the same status treatment the other two portals use.

import type { ReactNode } from "react";

import { Badge, cn } from "@pulseos/ui";

export type Tone = "success" | "warning" | "info" | "destructive" | "neutral" | "primary";

const dotClasses: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  info: "bg-info",
  destructive: "bg-destructive",
  neutral: "bg-muted-foreground",
  primary: "bg-primary",
};

export interface StatusBadgeProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}

export function StatusBadge({ tone = "neutral", children, className }: StatusBadgeProps) {
  return (
    <Badge variant={tone} className={cn("gap-1.5", className)}>
      <span className={cn("size-1.5 shrink-0 rounded-full", dotClasses[tone])} aria-hidden />
      {children}
    </Badge>
  );
}
