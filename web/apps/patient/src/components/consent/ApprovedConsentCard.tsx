// A previously approved consent, in the Card primitive's compact size so the approved list
// reads as secondary to the pending queue above it.
//
// View is presentational per spec.

import { Building2, Eye } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ApprovedConsent } from "@/data/consents";

export interface ApprovedConsentCardProps {
  consent: ApprovedConsent;
}

export function ApprovedConsentCard({ consent }: ApprovedConsentCardProps) {
  return (
    <Card size="sm" className="hover:bg-accent/40 transition-colors duration-150">
      <CardContent className="space-y-3">
        <div className="flex items-start gap-3">
          <IconChip icon={Building2} size="sm" />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground truncate text-sm font-medium">{consent.hospital}</h3>
            <p className="text-muted-foreground truncate text-xs">{consent.purpose}</p>
          </div>
          <StatusBadge tone="success">Approved</StatusBadge>
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-muted-foreground text-xs">
            Expires on <span className="text-foreground">{consent.expiresOn}</span>
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
