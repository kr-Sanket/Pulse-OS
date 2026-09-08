// One actor inside an origin group: a collapsible header, and their events beneath it.
//
// Presentational. The header carries the count and the latest activity so a reader can see
// what is inside without opening it — the whole point of collapsing by default.

import { ChevronRight, UserRound } from "lucide-react";

import { AuditTimelineItem } from "@/components/audit/AuditTimelineItem";
import { cn, formatRelativeTime } from "@pulseos/ui";

import type { ActorGroup } from "@/audit/view";

export interface AuditActorGroupProps {
  group: ActorGroup;
  expanded: boolean;
  onToggle: () => void;
}

export function AuditActorGroup({ group, expanded, onToggle }: AuditActorGroupProps) {
  const panelId = `actor-panel-${group.key}`;
  const lastIndex = group.events.length - 1;

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="hover:bg-accent/60 focus-visible:ring-ring/30 flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors outline-none focus-visible:ring-[3px]"
      >
        <ChevronRight
          className={cn(
            "text-muted-foreground size-4 shrink-0 transition-transform duration-150",
            expanded && "rotate-90",
          )}
          aria-hidden
        />
        <UserRound className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
          {group.name}
        </span>
        <span className="text-muted-foreground shrink-0 text-xs">
          {group.eventCount} {group.eventCount === 1 ? "event" : "events"}
        </span>
      </button>

      {expanded ? (
        <ol id={panelId} className="pl-4">
          {group.events.map((event, index) => (
            <AuditTimelineItem key={event.id} event={event} isLast={index === lastIndex} />
          ))}
        </ol>
      ) : (
        <p id={panelId} className="text-muted-foreground pl-11 text-xs">
          Latest {formatRelativeTime(group.latestAt)}
        </p>
      )}
    </div>
  );
}
