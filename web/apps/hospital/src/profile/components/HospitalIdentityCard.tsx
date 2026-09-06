// Which hospital the signed-in account administers: name, verification, and the facts that
// identify it on PulseOS.
//
// Shared by the dashboard, the My Hospital page and the post-registration panel — extracted
// once the second surface needed it, so the three cannot drift apart. Presentational:
// everything it renders was worded by profile/view.ts.

import { Building2 } from "lucide-react";

import { Card, CardContent, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import type { HospitalIdentityView } from "@/profile/view";

export interface HospitalIdentityCardProps {
  identity: HospitalIdentityView;
}

export function HospitalIdentityCard({ identity }: HospitalIdentityCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <IconChip icon={Building2} tone="solid" size="lg" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-foreground text-xl font-semibold tracking-tight">
                {identity.hospitalName}
              </h3>
              <StatusBadge tone={identity.verificationTone}>
                {identity.verificationLabel}
              </StatusBadge>
            </div>
            <p className="text-muted-foreground truncate text-sm">
              Administered by {identity.adminFullName}
            </p>
          </div>
        </div>

        <Separator />

        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          <Detail label="Hospital ID">
            <span className="font-mono text-[13px] tracking-tight">{identity.hospitalHid}</span>
          </Detail>
          <Detail label="Registered">{identity.registeredOn}</Detail>
          <Detail label="Address">
            <span className={identity.hasAddress ? undefined : "text-muted-foreground"}>
              {identity.address}
            </span>
          </Detail>
        </dl>
      </CardContent>
    </Card>
  );
}
