// Hospital dashboard — a placeholder that exists to prove the shell renders.
//
// Deliberately makes no API call and shows no data, not even a plausible-looking figure: a
// dashboard that invents numbers is harder to remove than one that admits it is empty. The
// hospital's identity, its verification state and its doctor roster all arrive with the
// slices named below, each wired to a real endpoint.

import { Card, CardContent } from "@pulseos/ui";

export function DashboardPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">
          Hospital Dashboard
        </h2>
      </div>

      <Card>
        <CardContent>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Hospital portal setup complete. Identity, doctor management and uploads will be added in
            subsequent slices.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
