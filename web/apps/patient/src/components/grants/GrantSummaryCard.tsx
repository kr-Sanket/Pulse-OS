// A grant the patient is not being asked to act on, in the Card primitive's compact size so
// these lists read as secondary to the active list above them.
//
// One card for three sections — expiring soon, revoked, lapsed — because they differ only in
// what the badge and the two facts say, and grants/view.ts has already worded those for the
// grant's own status.

import { Building2 } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Card, CardContent } from "@pulseos/ui";

import type { Tone } from "@/components/dashboard/StatusBadge";
import type { GrantGroupView } from "@/grants/view";

export interface GrantSummaryCardProps {
  grant: GrantGroupView;
  /** Overrides the grant's own badge — the Expiring Soon section says "Expiring", not
   * "Active", about a grant that is still active. */
  badgeLabel?: string;
  badgeTone?: Tone;
}

export function GrantSummaryCard({ grant, badgeLabel, badgeTone }: GrantSummaryCardProps) {
  return (
    <Card size="sm" className="transition-colors duration-150 hover:bg-accent/40">
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <IconChip icon={Building2} size="sm" />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground truncate text-sm font-medium">{grant.hospital}</h3>
            <p className="text-muted-foreground truncate text-xs">{grant.clinician}</p>
          </div>
          <StatusBadge tone={badgeTone ?? grant.statusTone}>
            {badgeLabel ?? grant.statusLabel}
          </StatusBadge>
        </div>

        <div className="flex items-baseline justify-between gap-3">
          <p className="text-foreground text-sm">{grant.summaryNote}</p>
          <p className="text-muted-foreground text-xs">{grant.summaryDetail}</p>
        </div>
      </CardContent>
    </Card>
  );
}
