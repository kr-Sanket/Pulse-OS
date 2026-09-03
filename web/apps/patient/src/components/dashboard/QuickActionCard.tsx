// A promoted action, rendered as a bordered tile so a row of them reads as one panel
// (the v0 dashboard's bottom-section treatment). Navigates only; it performs no work
// itself, so it stays reusable whatever the destination page ends up doing.

import { ChevronRight, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

export interface QuickActionCardProps {
  title: string;
  description: string;
  actionLabel: string;
  /** Internal route the tile leads to. */
  to: string;
  icon: LucideIcon;
}

export function QuickActionCard({
  title,
  description,
  actionLabel,
  to,
  icon: Icon,
}: QuickActionCardProps) {
  return (
    <Link
      to={to}
      className="group border-border/60 hover:border-primary/40 hover:bg-primary-muted/30 block rounded-xl border p-5 transition-all duration-150 hover:shadow-sm hover:shadow-black/[0.03]"
    >
      <div className="flex items-center gap-2">
        <Icon className="text-primary size-4 shrink-0" aria-hidden />
        <p className="text-foreground truncate text-sm font-medium">{title}</p>
      </div>
      <p className="text-muted-foreground mt-1.5 text-xs leading-relaxed">{description}</p>
      <p className="text-primary mt-3 flex items-center gap-1 text-xs font-medium">
        {actionLabel}
        <ChevronRight
          className="size-3 transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      </p>
    </Link>
  );
}
