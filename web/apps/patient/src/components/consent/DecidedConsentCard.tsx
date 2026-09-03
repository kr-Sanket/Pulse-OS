// A request that is no longer waiting on the patient, in the Card primitive's compact size
// so these lists read as secondary to the pending queue above them.
//
// One card for every closed outcome — approved, declined, expired, withdrawn — because they
// differ only in what the badge says. View is presentational: there is no per-request
// endpoint to open yet.

import { Building2, Eye } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ConsentRequestView } from "@/consent/view";

export interface DecidedConsentCardProps {
  request: ConsentRequestView;
}

export function DecidedConsentCard({ request }: DecidedConsentCardProps) {
  return (
    <Card size="sm" className="transition-colors duration-150 hover:bg-accent/40">
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <IconChip icon={Building2} size="sm" />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground truncate text-sm font-medium">{request.hospital}</h3>
            <p className="text-muted-foreground truncate text-xs">{request.purpose}</p>
          </div>
          <StatusBadge tone={request.statusTone}>{request.statusLabel}</StatusBadge>
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-muted-foreground text-xs">
            Requested on <span className="text-foreground">{request.requestedOn}</span>
          </p>
          <Button variant="ghost" size="xs" className="gap-1.5">
            <Eye className="size-3.5" aria-hidden />
            View
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
