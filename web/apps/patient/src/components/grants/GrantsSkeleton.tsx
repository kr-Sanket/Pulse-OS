// Placeholder cards while the listing loads. Mirrors ActiveGrantCard's geometry — chip,
// title row, the four-fact grid, two actions — so the list does not jump when the real
// grants land.

import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

const PLACEHOLDER_CARDS = ["first", "second"];
const PLACEHOLDER_FACTS = ["purpose", "records", "granted", "expires"];

export function GrantsSkeleton() {
  return (
    <div className="space-y-4" aria-busy role="status" aria-label="Loading active grants">
      {PLACEHOLDER_CARDS.map((card) => (
        <Card key={card}>
          <CardContent className="space-y-5">
            <div className="flex items-start gap-4">
              <Skeleton className="size-10 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-44 max-w-full" />
                <Skeleton className="h-3 w-32" />
              </div>
              <Skeleton className="h-5 w-16 rounded-4xl" />
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
              <Skeleton className="h-7 w-28 rounded-lg" />
              <Skeleton className="h-7 w-32 rounded-lg" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
