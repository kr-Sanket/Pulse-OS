// Placeholder for the identity card while GET /doctors/me is in flight. Shaped like the
// card it stands in for, so neither page reflows when the profile lands.

import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

const PLACEHOLDER_FACTS = ["hospital", "specialty", "registration"];

export function ClinicianIdentitySkeleton() {
  return (
    <Card className="[--card-spacing:--spacing(6)]" aria-busy role="status" aria-label="Loading">
      <CardContent className="space-y-6">
        <div className="flex items-center gap-5">
          <Skeleton className="size-11 shrink-0 rounded-xl" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-6 w-56 max-w-full" />
            <Skeleton className="h-4 w-40" />
          </div>
        </div>
        <Separator />
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          {PLACEHOLDER_FACTS.map((fact) => (
            <div key={fact} className="space-y-1.5">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-4 w-32 max-w-full" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
