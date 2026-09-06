// One doctor on the roster: who they are, where they stand, and the single action that
// standing offers.
//
// Presentational — the label, the tone, the button wording and the sentence explaining what
// the button does were all decided in doctors/view.ts. The effect line sits beside the button
// rather than behind a confirmation dialog: both calls are idempotent and reversible, and a
// sentence the administrator can read before pressing beats one they must dismiss after.

import { Stethoscope } from "lucide-react";

import { Button, Card, CardContent, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import type { DoctorView } from "@/doctors/view";

export interface DoctorCardProps {
  doctor: DoctorView;
  /** A status change is in flight for this card. */
  busy: boolean;
  /** Why the last status change on this card failed, if it did. */
  error: string | null;
  onAction: () => void;
}

export function DoctorCard({ doctor, busy, error, onAction }: DoctorCardProps) {
  const { action } = doctor;
  const effectId = `${doctor.id}-effect`;

  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Stethoscope} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{doctor.fullName}</h3>
            <p className="text-muted-foreground truncate text-sm">
              <span className={doctor.hasSpecialty ? undefined : "italic"}>{doctor.specialty}</span>
            </p>
          </div>
          <StatusBadge tone={doctor.statusTone}>{doctor.statusLabel}</StatusBadge>
        </div>

        <Separator />

        <dl className="grid gap-5 sm:grid-cols-2">
          <Detail label="Registration number">
            <span className="font-mono text-[13px] tracking-tight">
              {doctor.registrationNumber}
            </span>
          </Detail>
          <Detail label="Registered">{doctor.registeredOn}</Detail>
        </dl>

        <Separator />

        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <p id={effectId} className="text-muted-foreground max-w-xl text-xs leading-relaxed">
            {action.effect}
          </p>
          <Button
            variant={action.emphasis === "primary" ? "default" : "outline"}
            size="sm"
            className="shrink-0"
            disabled={busy}
            aria-describedby={effectId}
            onClick={onAction}
          >
            {busy ? action.busyLabel : action.label}
          </Button>
        </div>

        {error === null ? null : (
          <p role="alert" className="text-destructive text-sm leading-relaxed">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
