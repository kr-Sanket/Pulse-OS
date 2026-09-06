// Placeholder for the roster while GET /hospitals/me/doctors is in flight. Shaped like the
// cards it stands in for, so the page does not reflow when they land.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_CARDS = ["first", "second", "third"];

export function DoctorsSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading">
      {PLACEHOLDER_CARDS.map((card) => (
        <Card key={card}>
          <CardContent className="space-y-5">
            <div className="flex items-start gap-4">
              <Skeleton className="size-10 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-48 max-w-full" />
                <Skeleton className="h-3.5 w-32" />
              </div>
              <Skeleton className="h-5 w-24 shrink-0 rounded-4xl" />
            </div>
            <Separator />
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Skeleton className="h-2.5 w-24" />
                <Skeleton className="h-4 w-32" />
              </div>
              <div className="space-y-1.5">
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="h-4 w-28" />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
