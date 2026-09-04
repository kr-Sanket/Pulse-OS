// A Badge with a leading tone dot — the same status treatment the patient portal uses.

import type { ReactNode } from "react";

import { cn } from "@pulseos/ui";

import { Badge } from "@/components/ui/badge";

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
