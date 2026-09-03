// The patient's personal details as a definition list. Full Name and Email come from the
// authenticated identity; every other field is mock (src/data/profile.ts).

import { Detail } from "@/components/common/Detail";
import { Card, CardContent } from "@/components/ui/card";
import { personalInfoFor, type ProfileIdentity } from "@/data/profile";

export interface PersonalInfoCardProps {
  identity: ProfileIdentity;
}

export function PersonalInfoCard({ identity }: PersonalInfoCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent>
        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {personalInfoFor(identity).map((field) => (
            <Detail
              key={field.label}
              label={field.label}
              className={field.wide === true ? "sm:col-span-2 lg:col-span-3" : undefined}
            >
              {field.mono === true ? (
                <span className="font-mono text-[13px] tracking-tight">{field.value}</span>
              ) : (
                field.value
              )}
            </Detail>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
