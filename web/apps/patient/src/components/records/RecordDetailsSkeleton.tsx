// Placeholder for the summary panel while GET /records/{id} is in flight, shaped like
// RecordDetailsPanel so the column keeps its width and the page does not reflow.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_ROWS = ["hospital", "service-date", "added", "file", "size", "description"];

export function RecordDetailsSkeleton() {
  return (
    <Card className="sticky top-24" aria-busy role="status" aria-label="Loading record details">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-3.5">
          <Skeleton className="size-10 shrink-0 rounded-xl" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-4 w-40 max-w-full" />
            <Skeleton className="h-5 w-24 rounded-4xl" />
          </div>
        </div>

        <Separator />

        <div className="space-y-4">
          {PLACEHOLDER_ROWS.map((row) => (
            <div key={row} className="space-y-1.5">
              <Skeleton className="h-2.5 w-20" />
              <Skeleton className="h-3.5 w-36 max-w-full" />
            </div>
          ))}
        </div>

        <Separator />

        <Skeleton className="h-7 w-full rounded-lg" />
      </CardContent>
    </Card>
  );
}
