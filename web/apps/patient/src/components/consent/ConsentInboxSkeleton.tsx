// Placeholder cards while the inbox loads. Mirrors PendingRequestCard's geometry — chip,
// title row, the four-fact grid, two actions — so the queue does not jump when the real
// requests land.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_CARDS = ["first", "second"];
const PLACEHOLDER_FACTS = ["purpose", "records", "expires", "requested"];

export function ConsentInboxSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading consent requests">
      {PLACEHOLDER_CARDS.map((card) => (
        <Card key={card}>
          <CardContent className="space-y-5">
            <div className="flex items-start gap-4">
              <Skeleton className="size-10 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-44 max-w-full" />
                <Skeleton className="h-3 w-32" />
              </div>
              <Skeleton className="h-5 w-20 rounded-4xl" />
            </div>

            <Separator />

            <div className="grid gap-5 sm:grid-cols-2">
              {PLACEHOLDER_FACTS.map((fact) => (
                <div key={fact} className="space-y-1.5">
                  <Skeleton className="h-2.5 w-24" />
                  <Skeleton className="h-4 w-40 max-w-full" />
                </div>
              ))}
            </div>

            <div className="flex gap-2">
              <Skeleton className="h-7 w-24 rounded-lg" />
              <Skeleton className="h-7 w-24 rounded-lg" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
