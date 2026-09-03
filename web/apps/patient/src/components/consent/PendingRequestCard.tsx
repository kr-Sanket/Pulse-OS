// One pending access request, spacious enough to answer the four questions a patient needs
// before deciding: who is asking, why, what they would see, and for how long.
//
// Approve and Decline are presentational per spec — the endpoints exist
// (POST /access-requests/{id}/approve | reject) but wiring them is a later slice.

import { Building2, Check, X } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { PendingConsentRequest } from "@/data/consents";

export interface PendingRequestCardProps {
  request: PendingConsentRequest;
}

export function PendingRequestCard({ request }: PendingRequestCardProps) {
  return (
    <Card className="hover:shadow-md hover:shadow-black/[0.04] transition-shadow duration-150">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Building2} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{request.hospital}</h3>
            <p className="text-muted-foreground truncate text-sm">{request.doctor}</p>
          </div>
          <StatusBadge tone="warning">Pending</StatusBadge>
        </div>

        <Separator />

        <dl className="grid gap-5 sm:grid-cols-2">
          <Detail label="Purpose">{request.purpose}</Detail>
          <Detail label="Requested records">
            <span className="flex flex-wrap gap-1.5">
              {request.categories.map((category) => (
                <Badge key={category} variant="secondary">
                  {category}
                </Badge>
              ))}
            </span>
          </Detail>
          <Detail label="Duration">{request.duration}</Detail>
          <Detail label="Requested">{request.requestedAgo}</Detail>
        </dl>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button size="sm" className="justify-center gap-2 sm:w-auto">
            <Check className="size-4" aria-hidden />
            Approve
          </Button>
          <Button variant="outline" size="sm" className="justify-center gap-2 sm:w-auto">
            <X className="size-4" aria-hidden />
            Decline
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
