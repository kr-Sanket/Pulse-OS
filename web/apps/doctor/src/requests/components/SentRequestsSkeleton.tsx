// Placeholder cards while the listing loads. Mirrors SentRequestCard's geometry — chip,
// title row, the fact grid — so the page does not jump when the real requests land.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_CARDS = ["first", "second"];
const PLACEHOLDER_FACTS = ["purpose", "records", "requested", "deadline"];

export function SentRequestsSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading your requests">
      {PLACEHOLDER_CARDS.map((card) => (
        <Card key={card}>
          <CardContent className="space-y-5">
            <div className="flex items-start gap-4">
              <Skeleton className="size-10 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-48 max-w-full" />
                <Skeleton className="h-3 w-32" />
              </div>
              <Skeleton className="h-5 w-28 rounded-4xl" />
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
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
