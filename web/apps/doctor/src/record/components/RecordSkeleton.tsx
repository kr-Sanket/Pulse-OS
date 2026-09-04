// Placeholders while the record loads. Mirrors the geometry of the metadata card and the
// file card — badge row, separator, two-column fact grid, then the action block — so the
// page does not jump when the record lands.

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

const PLACEHOLDER_FACTS = ["service", "uploaded", "origin", "hospital", "filename", "file"];

export function RecordSkeleton() {
  return (
    <div className="space-y-6" aria-busy role="status" aria-label="Loading this record">
      <Card>
        <CardHeader>
          <Skeleton className="h-4 w-32" />
        </CardHeader>
        <CardContent className="space-y-5 pt-1">
          <div className="flex items-center gap-2">
            <Skeleton className="h-5 w-16 rounded-4xl" />
            <Skeleton className="h-4 w-44 max-w-full" />
            <Skeleton className="h-5 w-20 rounded-4xl" />
          </div>

          <Separator />

          <div className="grid gap-5 sm:grid-cols-2">
            {PLACEHOLDER_FACTS.map((fact) => (
              <div key={fact} className="space-y-1.5">
                <Skeleton className="h-2.5 w-24" />
                <Skeleton className="h-4 w-36 max-w-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <Skeleton className="h-4 w-16" />
        </CardHeader>
        <CardContent className="space-y-4 pt-1">
          <Skeleton className="h-9 w-32 rounded-lg" />
          <Skeleton className="h-3 w-48 max-w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
