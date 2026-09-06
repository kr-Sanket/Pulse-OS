// A list of recent items inside a section card. Rows optionally link, and skeleton rows
// stand in while entries are absent — so the same component serves the mock data now and
// a real fetch later without changing shape.

import { ArrowRight, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, Skeleton } from "@pulseos/ui";

import type { ActivityEntry } from "@/dashboard/view";

import { IconChip } from "./IconChip";
import { SectionCard } from "./SectionCard";

export interface ActivityListProps {
  title: string;
  /** Optional "View all" style link in the section header. */
  actionLabel?: string;
  actionTo?: string;
  /** Undefined means "still loading" and renders placeholder rows. */
  entries?: readonly ActivityEntry[];
  skeletonRows?: number;
  emptyMessage?: string;
}

function ActivitySkeletonRow() {
  return (
    <div className="flex items-center gap-5 py-4">
      <Skeleton className="size-10 shrink-0 rounded-xl" />
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-3 w-1/3" />
      </div>
      <Skeleton className="h-5 w-16 shrink-0" />
    </div>
  );
}

function EntryBody({ entry }: { entry: ActivityEntry }) {
  return (
    <>
      <IconChip icon={entry.icon} />
      <div className="min-w-0 flex-1">
        <p className="text-foreground group-hover:text-primary truncate text-sm font-medium transition-colors">
          {entry.title}
        </p>
        <p className="text-muted-foreground truncate text-xs">{entry.description}</p>
      </div>
      {entry.badgeLabel === undefined ? null : (
        <Badge variant={entry.tone} className="hidden sm:inline-flex">
          {entry.badgeLabel}
        </Badge>
      )}
      {entry.timestamp === undefined ? null : (
        <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">
          {entry.timestamp}
        </span>
      )}
      {entry.to === undefined ? null : (
        <ArrowRight
          className="text-muted-foreground size-4 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      )}
    </>
  );
}

export function ActivityList({
  title,
  actionLabel,
  actionTo,
  entries,
  skeletonRows = 3,
  emptyMessage = "Nothing yet.",
}: ActivityListProps) {
  const action =
    actionLabel !== undefined && actionTo !== undefined
      ? { label: actionLabel, to: actionTo, icon: ChevronRight }
      : undefined;

  return (
    <SectionCard title={title} action={action}>
      {entries === undefined ? (
        <div className="divide-border/60 divide-y">
          {Array.from({ length: skeletonRows }, (_, index) => (
            <ActivitySkeletonRow key={index} />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">{emptyMessage}</p>
      ) : (
        <ul className="divide-border/60 divide-y">
          {entries.map((entry) => (
            <li key={entry.id}>
              {entry.to === undefined ? (
                <div className="group flex items-center gap-5 py-4">
                  <EntryBody entry={entry} />
                </div>
              ) : (
                <Link
                  to={entry.to}
                  className="group flex items-center gap-5 py-4 transition-colors duration-150"
                >
                  <EntryBody entry={entry} />
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
