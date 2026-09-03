// Placeholder for one figure while its source loads. Mirrors StatCard's geometry — label
// row, value, note — so the four-up row does not resize when the numbers arrive.

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export function StatCardSkeleton() {
  return (
    <Card className="[--card-spacing:--spacing(5)]" aria-busy role="status" aria-label="Loading">
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="size-9 shrink-0 rounded-lg" />
        </div>
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-5 w-28 rounded-4xl" />
      </CardContent>
    </Card>
  );
}
