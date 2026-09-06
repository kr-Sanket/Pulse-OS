// One request the clinician raised: who it is about, what was asked for, and where it got to.
//
// Presentational — every string it renders was worded by requests/view.ts. Read-only by
// design: a request cannot be cancelled, edited or re-sent from here, so the card carries no
// actions at all.

import { UserRound } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { Badge, Card, CardContent, Separator } from "@pulseos/ui";

import type { SentRequestView } from "@/requests/view";

export interface SentRequestCardProps {
  request: SentRequestView;
}

export function SentRequestCard({ request }: SentRequestCardProps) {
  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={UserRound} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground truncate font-mono text-[15px] font-medium tracking-tight">
              {request.patientHealthId}
            </h3>
            <p className="text-muted-foreground truncate text-sm">{request.requestedAgo}</p>
          </div>
          <StatusBadge tone={request.statusTone}>{request.statusLabel}</StatusBadge>
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
          <Detail label="Requested on">{request.requestedOn}</Detail>
          {request.expiresIn === null ? null : (
            <Detail label="Deadline">{request.expiresIn}</Detail>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
