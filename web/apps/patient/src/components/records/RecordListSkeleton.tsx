// Placeholder cards while GET /records is in flight. Mirrors RecordCard's geometry — icon
// chip, title row, meta row, description, action — so the list does not jump when the real
// data lands.

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const PLACEHOLDER_ROWS = ["first", "second", "third"];

export function RecordListSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading records">
      {PLACEHOLDER_ROWS.map((row) => (
        <Card key={row}>
          <CardContent className="flex gap-4">
            <Skeleton className="size-10 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <Skeleton className="h-4 w-48 max-w-full" />
                <Skeleton className="h-5 w-24 rounded-4xl" />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                <Skeleton className="h-3 w-32" />
                <Skeleton className="h-3 w-24" />
              </div>
              <div className="space-y-1.5">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-2/3" />
              </div>
              <Skeleton className="h-7 w-28 rounded-lg" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
