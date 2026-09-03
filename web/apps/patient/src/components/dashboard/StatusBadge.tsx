// A Badge with a leading tone dot. Thin wrapper by design: the tone styling lives in the
// Badge variants so it stays available to the rest of the portal.

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

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
