// Who the signed-in clinician is: name, status, where they practise, and the three facts
// that identify them professionally.
//
// Shared by the dashboard and the profile page — extracted when the second page needed the
// same panel, so the two cannot drift apart. Presentational: everything it renders was
// worded by profile/view.ts.

import { IdCard } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { DoctorIdentityView } from "@/profile/view";

export interface ClinicianIdentityCardProps {
  identity: DoctorIdentityView;
}

export function ClinicianIdentityCard({ identity }: ClinicianIdentityCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <IconChip icon={IdCard} tone="solid" size="lg" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-foreground text-xl font-semibold tracking-tight">
                {identity.fullName}
              </h3>
              <StatusBadge tone={identity.statusTone}>{identity.statusLabel}</StatusBadge>
            </div>
            <p className="text-muted-foreground truncate text-sm">{identity.hospitalName}</p>
          </div>
        </div>

        <Separator />

        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          <Detail label="Hospital">{identity.hospitalName}</Detail>
          <Detail label="Specialty">
            <span className={identity.hasSpecialty ? undefined : "text-muted-foreground"}>
              {identity.specialty}
            </span>
          </Detail>
          <Detail label="Registration number">
            <span className="font-mono text-[13px] tracking-tight">
              {identity.registrationNumber}
            </span>
          </Detail>
        </dl>
      </CardContent>
    </Card>
  );
}
