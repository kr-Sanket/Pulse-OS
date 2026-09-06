// How this account is secured. Informational only — sign-out lives in the sidebar footer,
// and nothing here is actionable.
//
// Every fact is one the app can stand behind: sign-in is Google's, and the profile above
// loaded under this token. Last login and email verification are Firebase Admin facts the
// API does not expose, so they are not claimed — see profile/view.ts.

import { Detail } from "@/components/common/Detail";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Card, CardContent } from "@pulseos/ui";

import { securityFacts, type ProfileIdentity } from "@/profile/view";

export interface SecurityCardProps {
  identity: ProfileIdentity;
}

export function SecurityCard({ identity }: SecurityCardProps) {
  return (
    <Card className="h-full [--card-spacing:--spacing(6)]">
      <CardContent>
        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
          {securityFacts(identity).map((fact) => (
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
