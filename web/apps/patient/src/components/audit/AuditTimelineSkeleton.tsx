// Placeholder rail while the trail loads. Mirrors AuditTimelineItem's geometry — node,
// connector, card with a two-fact grid and a timestamp row — so the timeline does not jump
// when the real events land.

import { Card, CardContent, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_ITEMS = ["first", "second", "third"];
const PLACEHOLDER_FACTS = ["records", "hash"];

export function AuditTimelineSkeleton() {
  return (
    <ol aria-busy role="status" aria-label="Loading audit history">
      {PLACEHOLDER_ITEMS.map((item, index) => (
        <li key={item} className="flex gap-4">
          <div className="flex flex-col items-center" aria-hidden>
            <Skeleton className="size-9 shrink-0 rounded-lg" />
            {index === PLACEHOLDER_ITEMS.length - 1 ? null : (
              <span className="bg-border/70 mt-2 w-px flex-1" />
            )}
          </div>
          <div className="min-w-0 flex-1 pb-6">
            <Card>
              <CardContent className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-2">
                    <Skeleton className="h-4 w-40 max-w-full" />
                    <Skeleton className="h-3 w-28" />
                  </div>
                  <Skeleton className="h-5 w-24 rounded-4xl" />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  {PLACEHOLDER_FACTS.map((fact) => (
                    <div key={fact} className="space-y-1.5">
                      <Skeleton className="h-2.5 w-20" />
                      <Skeleton className="h-4 w-32 max-w-full" />
                    </div>
                  ))}
                </div>
                <div className="flex gap-4">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-3 w-16" />
                </div>
              </CardContent>
            </Card>
          </div>
        </li>
      ))}
    </ol>
  );
}
