// The dashboard's signature panel: the AI health summary. Gradient surface, solid brand
// icon chip, headline with a qualifier badge, prose body, provenance footnote.

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

import { IconChip } from "./IconChip";

export interface HeroCardProps {
  icon: LucideIcon;
  title: string;
  /** Short qualifier shown beside the title, e.g. "AI summary". */
  badgeLabel?: string;
  children: ReactNode;
  /** Provenance line in small muted type. */
  footnote?: string;
}

export function HeroCard({ icon, title, badgeLabel, children, footnote }: HeroCardProps) {
  return (
    <Card className="border-primary/20 from-primary-muted/45 to-card overflow-hidden rounded-2xl bg-gradient-to-br [--card-spacing:--spacing(6)]">
      <CardContent className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <IconChip icon={icon} tone="solid" size="xl" />
        <div className="flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-foreground text-base font-semibold">{title}</h2>
            {badgeLabel === undefined ? null : <Badge variant="primary">{badgeLabel}</Badge>}
          </div>
          <p className="text-foreground/80 text-pretty text-[15px] leading-7">{children}</p>
          {footnote === undefined ? null : (
            <p className="text-muted-foreground text-xs">{footnote}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
