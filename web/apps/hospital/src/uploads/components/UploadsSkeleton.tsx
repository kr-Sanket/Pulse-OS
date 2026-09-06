// Placeholder cards while the listing loads. Mirrors UploadRecordCard's geometry — chip,
// title row, status badge, the three-column fact grid — so the page does not jump when the
// real records land.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const PLACEHOLDER_CARDS = ["first", "second", "third"];
const PLACEHOLDER_FACTS = ["service", "origin", "uploaded"];

export function UploadsSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading uploaded records">
      {PLACEHOLDER_CARDS.map((card) => (
        <Card key={card}>
          <CardContent className="space-y-5">
            <div className="flex items-start gap-4">
              <Skeleton className="size-10 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-52 max-w-full" />
                <Skeleton className="h-3 w-36" />
              </div>
              <Skeleton className="h-5 w-20 shrink-0 rounded-4xl" />
            </div>

            <Separator />

            <div className="grid gap-5 sm:grid-cols-3">
              {PLACEHOLDER_FACTS.map((fact) => (
                <div key={fact} className="space-y-1.5">
                  <Skeleton className="h-2.5 w-24" />
                  <Skeleton className="h-4 w-28" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
