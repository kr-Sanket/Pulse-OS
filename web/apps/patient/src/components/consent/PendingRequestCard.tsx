// One pending access request, spacious enough to answer the four questions a patient needs
// before deciding: who is asking, why, what they would see, and by when it lapses.
//
// Presentational: the page owns the request state and the in-flight answer, this renders
// them and reports which button was pressed. Approve and Decline send exactly the
// categories the request asked for, which is why the card passes them back untouched.

import { Building2, Check, X } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { DecisionKind } from "@/consent/api";
import type { ConsentRequestView } from "@/consent/view";

export interface PendingRequestCardProps {
  request: ConsentRequestView;
  /** Which answer is in flight for this request, if any. */
  busy: DecisionKind | null;
  /** Why the last answer to this request failed, if it did. */
  error: string | null;
  onDecide: (kind: DecisionKind) => void;
}

export function PendingRequestCard({ request, busy, error, onDecide }: PendingRequestCardProps) {
  const answering = busy !== null;

  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Building2} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{request.hospital}</h3>
            <p className="text-muted-foreground truncate text-sm">{request.clinician}</p>
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
          <Detail label="Request expires">{request.expiresOn}</Detail>
          <Detail label="Requested">{request.requestedAgo}</Detail>
        </dl>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button
            size="sm"
            className="justify-center gap-2 sm:w-auto"
            disabled={answering}
            onClick={() => onDecide("approve")}
          >
            <Check className="size-4" aria-hidden />
            {busy === "approve" ? "Approving…" : "Approve"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="justify-center gap-2 sm:w-auto"
            disabled={answering}
            onClick={() => onDecide("reject")}
          >
            <X className="size-4" aria-hidden />
            {busy === "reject" ? "Declining…" : "Decline"}
          </Button>
        </div>

        {error === null ? null : (
          <p role="alert" className="text-destructive text-sm leading-relaxed">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
