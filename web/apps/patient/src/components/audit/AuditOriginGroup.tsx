// One origin — a hospital, the patient's own activity, or the unattributed events — with
// its actors nested inside.
//
// Three kinds share this component because they are the same shape to a reader, but they
// are not the same claim: only `hospital` names an organisation the trail actually recorded.
// `unattributed` carries a note saying why it has no name, so an absent attribution never
// reads as a missing hospital or, worse, gets mistaken for one.
//
// The count is the events **loaded so far**. The API publishes no lifetime total, and
// presenting a page total as one would misstate a compliance record.

import { Building2, ChevronRight, HelpCircle, UserRound } from "lucide-react";

import { AuditActorGroup } from "@/components/audit/AuditActorGroup";
import { AuditTimelineItem } from "@/components/audit/AuditTimelineItem";
import { Badge, Card, CardContent, cn, formatRelativeTime } from "@pulseos/ui";

import { UNATTRIBUTED_NOTE, type OriginGroup } from "@/audit/view";

export interface AuditOriginGroupProps {
  group: OriginGroup;
  expanded: boolean;
  onToggle: () => void;
  isActorExpanded: (actorKey: string) => boolean;
  onToggleActor: (actorKey: string) => void;
}

const ICONS = {
  hospital: Building2,
  self: UserRound,
  unattributed: HelpCircle,
} as const;

export function AuditOriginGroup({
  group,
  expanded,
  onToggle,
  isActorExpanded,
  onToggleActor,
}: AuditOriginGroupProps) {
  const panelId = `origin-panel-${group.key}`;
  const Icon = ICONS[group.kind];
  // The patient's own activity has exactly one actor — themselves — and the heading already
  // says so, so the actor level would be a second row of the same word. Every other kind
  // keeps it: an unattributed group can hold several clinicians, and naming them is the
  // only identification those events have.
  const flatten = group.kind === "self";
  const events = flatten ? group.actors.flatMap((actor) => actor.events) : [];
  const lastIndex = events.length - 1;

  return (
    <Card>
      <CardContent className="space-y-4">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={panelId}
          className="hover:bg-accent/50 focus-visible:ring-ring/30 -m-1.5 flex w-[calc(100%+0.75rem)] items-center gap-3 rounded-lg p-1.5 text-left transition-colors outline-none focus-visible:ring-[3px]"
        >
          <ChevronRight
            className={cn(
              "text-muted-foreground size-4 shrink-0 transition-transform duration-150",
              expanded && "rotate-90",
            )}
            aria-hidden
          />
          <Icon className="text-primary size-5 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="text-foreground block truncate text-[15px] font-medium">
              {group.title}
            </span>
            <span className="text-muted-foreground block text-xs">
              Latest activity {formatRelativeTime(group.latestAt)}
            </span>
          </span>
          <Badge variant="info">
            {group.eventCount} {group.eventCount === 1 ? "event" : "events"}
          </Badge>
        </button>

        {expanded ? (
          <div id={panelId} className="space-y-4 border-t pt-4">
            {group.kind === "unattributed" ? (
              <p className="text-muted-foreground text-xs leading-relaxed">{UNATTRIBUTED_NOTE}</p>
            ) : null}
            {flatten ? (
              <ol>
                {events.map((event, index) => (
                  <AuditTimelineItem key={event.id} event={event} isLast={index === lastIndex} />
                ))}
              </ol>
            ) : (
              group.actors.map((actor) => (
                <AuditActorGroup
                  key={actor.key}
                  group={actor}
                  expanded={isActorExpanded(actor.key)}
                  onToggle={() => onToggleActor(actor.key)}
                />
              ))
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
