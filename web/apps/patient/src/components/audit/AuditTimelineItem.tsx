// One entry in the access timeline: a node on a vertical rail, with the event details in a
// card beside it.
//
// The rail is drawn per item rather than as one absolute line behind the list, so it always
// matches the real height of the card next to it — no magic offsets to keep in sync.
//
// Presentational: everything it renders is already worded by audit/view.ts, including the
// action label, who the actor was and whether a category was recorded.

import { CalendarDays, Clock } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge, Card, CardContent } from "@pulseos/ui";

import type { AuditEventView } from "@/audit/view";

export interface AuditTimelineItemProps {
  event: AuditEventView;
  /** The last item draws no connector below its node. */
  isLast?: boolean;
}

export function AuditTimelineItem({ event, isLast = false }: AuditTimelineItemProps) {
  return (
    <li className="flex gap-4">
      <div className="flex flex-col items-center" aria-hidden>
        <IconChip icon={event.icon} size="sm" />
        {isLast ? null : <span className="bg-border/70 mt-2 w-px flex-1" />}
      </div>

      <div className="min-w-0 flex-1 pb-6">
        <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
              <div className="min-w-0">
                <h3 className="text-foreground text-[15px] font-medium">{event.origin}</h3>
                {event.actor === null ? null : (
                  <p className="text-muted-foreground truncate text-sm">{event.actor}</p>
                )}
              </div>
              <StatusBadge tone={event.actionTone}>{event.actionLabel}</StatusBadge>
            </div>

            <dl className="grid gap-4 sm:grid-cols-2">
              <Detail label="Records">
                {event.hasCategory ? (
                  <Badge variant="secondary">{event.category}</Badge>
                ) : (
                  <span className="text-muted-foreground">{event.category}</span>
                )}
              </Detail>
              <Detail label="Verification hash">
                <span
                  className="text-muted-foreground font-mono text-[13px] tracking-tight"
                  title={event.eventHash}
                >
                  {event.hashPreview}
                </span>
              </Detail>
            </dl>

            <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
              <span className="flex items-center gap-1.5">
                <CalendarDays className="size-3.5 shrink-0" aria-hidden />
                {event.date}
              </span>
              <span className="flex items-center gap-1.5">
                <Clock className="size-3.5 shrink-0" aria-hidden />
                {event.time}
              </span>
            </div>
          </CardContent>
        </Card>
      </div>
    </li>
  );
}
