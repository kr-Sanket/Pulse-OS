// The patient's personal details as a definition list.
//
// Name, date of birth, gender and Health ID come from GET /patients/me; email from the
// identity provider. The rest have no backend column yet and say so — see profile/view.ts.

import { Detail } from "@/components/common/Detail";
import { Card, CardContent } from "@pulseos/ui";

import { personalInfoFor, type ProfileIdentity } from "@/profile/view";
import type { PatientProfile } from "@pulseos/api-client";

export interface PersonalInfoCardProps {
  profile: PatientProfile;
  identity: ProfileIdentity;
}

export function PersonalInfoCard({ profile, identity }: PersonalInfoCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent>
        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {personalInfoFor(profile, identity).map((field) => (
            <Detail
              key={field.label}
              label={field.label}
              className={field.wide === true ? "sm:col-span-2 lg:col-span-3" : undefined}
            >
              {field.mono === true ? (
                <span className="font-mono text-[13px] tracking-tight">{field.value}</span>
              ) : (
                <span className={field.missing === true ? "text-muted-foreground" : undefined}>
                  {field.value}
                </span>
              )}
            </Detail>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
