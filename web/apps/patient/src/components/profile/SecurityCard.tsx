// How this account is secured. Informational only — sign-out lives in the sidebar footer,
// and nothing here is actionable.

import { Detail } from "@/components/common/Detail";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { SECURITY_FACTS } from "@/data/profile";

export function SecurityCard() {
  return (
    <Card className="h-full [--card-spacing:--spacing(6)]">
      <CardContent>
        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
          {SECURITY_FACTS.map((fact) => (
            <Detail key={fact.label} label={fact.label}>
              {fact.tone === undefined ? (
                fact.value
              ) : (
                <StatusBadge tone={fact.tone}>{fact.value}</StatusBadge>
              )}
            </Detail>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
