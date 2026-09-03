// "Expiring soon": the grants closest to lapsing. Occupies the slot the v0 dashboard
// gave to upcoming appointments, using the same icon-chip + three-line row treatment.

import { CalendarClock } from "lucide-react";

import type { ExpiringGrant } from "@/data/dashboard";

import { IconChip } from "./IconChip";
import { SectionCard } from "./SectionCard";

export interface ExpiringGrantsCardProps {
  grants: readonly ExpiringGrant[];
}

export function ExpiringGrantsCard({ grants }: ExpiringGrantsCardProps) {
  return (
    <SectionCard title="Expiring soon" icon={CalendarClock} contentClassName="space-y-4 pt-1">
      {grants.length === 0 ? (
        <p className="text-muted-foreground py-2 text-sm">No grants are close to expiring.</p>
      ) : (
        grants.map((grant) => (
          <div key={grant.id} className="flex items-start gap-3.5">
            <IconChip icon={grant.icon} size="sm" />
            <div className="min-w-0">
              <p className="text-foreground truncate text-sm font-medium">{grant.grantee}</p>
              <p className="text-muted-foreground truncate text-xs">{grant.scope}</p>
              <p className="text-muted-foreground text-xs">{grant.expiresIn}</p>
            </div>
          </div>
        ))
      )}
    </SectionCard>
  );
}
