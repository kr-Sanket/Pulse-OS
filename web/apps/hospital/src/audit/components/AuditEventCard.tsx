// One audit event, as the hospital sees it.
//
// Presentational — every string was worded by audit/view.ts. It shows what the endpoint
// returned and nothing more: no patient, no hospital, no digest, no filename or category.
// The record reference is an identifier, deliberately not a description; there is nothing to
// click through to, because opening the record would be a fresh audited read.

import { ScrollText } from "lucide-react";

import { Card, CardContent } from "@pulseos/ui";

import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import type { AuditEventView } from "@/audit/view";

export interface AuditEventCardProps {
  event: AuditEventView;
}

export function AuditEventCard({ event }: AuditEventCardProps) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4">
        <IconChip icon={ScrollText} />

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <StatusBadge tone={event.actionTone}>{event.actionLabel}</StatusBadge>
            {event.record === null ? null : (
              <span className="text-muted-foreground text-xs">
                Record{" "}
                <span className="text-foreground font-mono text-[12px] tracking-tight">
                  {event.record}
                </span>
              </span>
            )}
          </div>
          <p className="text-foreground truncate text-sm">
            {event.actor}
            {event.role === null ? null : (
              <span className="text-muted-foreground"> · {event.role}</span>
            )}
          </p>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-foreground text-xs">{event.date}</p>
          <p className="text-muted-foreground text-xs">{event.time}</p>
        </div>
      </CardContent>
    </Card>
  );
}
