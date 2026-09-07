// Placeholder rows while the first page loads. Mirrors AuditEventCard's geometry — chip,
// badge row, actor line, right-aligned timestamp — so the page does not jump when the trail
// lands.

import { Card, CardContent, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_ROWS = ["first", "second", "third", "fourth", "fifth"];

export function AuditSkeleton() {
  return (
    <div className="space-y-3" aria-busy role="status" aria-label="Loading audit history">
      {PLACEHOLDER_ROWS.map((row) => (
        <Card key={row}>
          <CardContent className="flex items-start gap-4">
            <Skeleton className="size-10 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-5 w-36 rounded-4xl" />
              <Skeleton className="h-4 w-48 max-w-full" />
            </div>
            <div className="shrink-0 space-y-1.5 text-right">
              <Skeleton className="ml-auto h-3 w-20" />
              <Skeleton className="ml-auto h-3 w-12" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
