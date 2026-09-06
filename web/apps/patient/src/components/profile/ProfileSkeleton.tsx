// Placeholder for the whole account view while the profile bootstrap runs. Shaped like the
// cards it stands in for — summary, personal information, then the two-up row — so the
// page does not reflow when the real data lands.

import { Card, CardContent, Separator, Skeleton } from "@pulseos/ui";

const SUMMARY_FACTS = ["health-id", "status", "member-since"];
const PERSONAL_FIELDS = ["name", "email", "phone", "dob", "gender", "blood", "id", "nationality"];
const PAIRED_FIELDS = ["one", "two", "three", "four"];

export function ProfileSkeleton() {
  return (
    <div className="space-y-10" aria-busy role="status" aria-label="Loading your profile">
      <Card className="[--card-spacing:--spacing(6)]">
        <CardContent className="space-y-6">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
            <Skeleton className="size-20 shrink-0 rounded-full" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-6 w-56 max-w-full" />
              <Skeleton className="h-4 w-64 max-w-full" />
            </div>
          </div>
          <Separator />
          <div className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
            {SUMMARY_FACTS.map((fact) => (
              <div key={fact} className="space-y-1.5">
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="h-4 w-32 max-w-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Skeleton className="h-4 w-40" />
        <Card className="[--card-spacing:--spacing(6)]">
          <CardContent>
            <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
              {PERSONAL_FIELDS.map((field) => (
                <div key={field} className="space-y-1.5">
                  <Skeleton className="h-2.5 w-24" />
                  <Skeleton className="h-4 w-36 max-w-full" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        {["emergency", "security"].map((section) => (
          <div key={section} className="space-y-4">
            <Skeleton className="h-4 w-36" />
            <Card className="h-full [--card-spacing:--spacing(6)]">
              <CardContent>
                <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
                  {PAIRED_FIELDS.map((field) => (
                    <div key={field} className="space-y-1.5">
                      <Skeleton className="h-2.5 w-24" />
                      <Skeleton className="h-4 w-28 max-w-full" />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        ))}
      </div>
    </div>
  );
}
