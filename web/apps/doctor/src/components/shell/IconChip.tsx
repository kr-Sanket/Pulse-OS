// The tinted rounded square an icon sits in. Mirrors the patient portal's chip so the two
// surfaces read as one product.

import type { LucideIcon } from "lucide-react";

import { cn } from "@pulseos/ui";

export type IconChipTone = "muted" | "solid";
export type IconChipSize = "sm" | "md" | "lg";

const toneClasses: Record<IconChipTone, string> = {
  muted: "bg-primary-muted text-primary",
  solid: "bg-primary text-primary-foreground shadow-sm",
};

const sizeClasses: Record<IconChipSize, string> = {
  sm: "size-9 rounded-lg [&>svg]:size-4",
  md: "size-10 rounded-xl [&>svg]:size-5",
  lg: "size-11 rounded-xl [&>svg]:size-5",
};

export interface IconChipProps {
  icon: LucideIcon;
  tone?: IconChipTone;
  size?: IconChipSize;
  className?: string;
}

export function IconChip({ icon: Icon, tone = "muted", size = "md", className }: IconChipProps) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center",
        toneClasses[tone],
        sizeClasses[size],
        className,
      )}
    >
      <Icon aria-hidden />
    </span>
  );
}
