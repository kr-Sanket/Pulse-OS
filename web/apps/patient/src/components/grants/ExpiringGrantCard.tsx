// A grant close to lapsing, in the Card primitive's compact size so this section reads as
// secondary to the active list above it. Days remaining is the headline fact.

import { Building2 } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import type { ExpiringSoonGrant } from "@/data/grants";

export interface ExpiringGrantCardProps {
  grant: ExpiringSoonGrant;
}

export function ExpiringGrantCard({ grant }: ExpiringGrantCardProps) {
  const dayLabel = grant.daysRemaining === 1 ? "day" : "days";

  return (
    <Card size="sm" className="transition-colors duration-150 hover:bg-accent/40">
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <IconChip icon={Building2} size="sm" />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground truncate text-sm font-medium">{grant.hospital}</h3>
            <p className="text-muted-foreground truncate text-xs">{grant.purpose}</p>
          </div>
          <StatusBadge tone="warning">Expiring</StatusBadge>
        </div>

        <div className="flex items-baseline justify-between gap-3">
          <p className="text-foreground text-sm">
            <span className="font-semibold tabular-nums">{grant.daysRemaining}</span> {dayLabel}{" "}
            remaining
          </p>
          <p className="text-muted-foreground text-xs">Expires {grant.expiresOn}</p>
        </div>
      </CardContent>
    </Card>
  );
}
