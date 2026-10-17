// Renders a hospital account within the System Admin verification queue.
//
// Shows identifier, name, address, current verification status, and verification action.
// Rejection is intentionally omitted because the backend domain model and API do not support it.

import { Building2, CheckCircle2, Clock } from "lucide-react";

import { Badge, Button, Card, CardContent, formatInstantDate } from "@pulseos/ui";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { formatVerifierId, VERIFICATION_STATUS_CONFIG, type HospitalReviewItem } from "../view";

export interface HospitalVerificationCardProps {
  hospital: HospitalReviewItem;
  busy: boolean;
  onVerify: (hid: string) => void;
}

export function HospitalVerificationCard({
  hospital,
  busy,
  onVerify,
}: HospitalVerificationCardProps) {
  const isVerified = hospital.status === "VERIFIED";
  const statusConfig = VERIFICATION_STATUS_CONFIG[hospital.status];

  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-4 pt-5 pb-5">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="bg-primary/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg mt-0.5">
              <Building2 className="size-5" aria-hidden />
            </span>
            <div className="space-y-1 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-foreground text-[15px] font-semibold">{hospital.name}</h3>
                <Badge variant="outline" className="font-mono text-xs font-normal">
                  {hospital.hid}
                </Badge>
              </div>
              <p className="text-muted-foreground text-xs leading-relaxed truncate">
                {hospital.address ?? "Address not recorded"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 self-start sm:self-auto">
            <StatusBadge tone={statusConfig.tone}>{statusConfig.label}</StatusBadge>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t text-xs">
          <div className="text-muted-foreground flex items-start gap-1.5 min-w-0">
            {isVerified ? (
              <div className="space-y-0.5 min-w-0">
                <div className="flex items-center gap-1.5">
                  <CheckCircle2
                    className="size-3.5 text-emerald-600 dark:text-emerald-400 shrink-0"
                    aria-hidden
                  />
                  <span>Verified: Organization can register doctors and upload records.</span>
                </div>
                {hospital.verifiedAt || hospital.verifiedByUserId ? (
                  <p className="text-muted-foreground/80 pl-5 text-[11px]">
                    Verified
                    {hospital.verifiedAt ? ` on ${formatInstantDate(hospital.verifiedAt)}` : ""}
                    {hospital.verifiedByUserId
                      ? ` by Admin (${formatVerifierId(hospital.verifiedByUserId)})`
                      : ""}
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <Clock
                  className="size-3.5 text-amber-600 dark:text-amber-400 shrink-0"
                  aria-hidden
                />
                <span>
                  Awaiting verification: Doctors and record uploads are currently blocked.
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {isVerified ? (
              <Button
                variant="outline"
                size="sm"
                disabled
                className="h-8 text-xs font-medium opacity-80"
              >
                <CheckCircle2 className="size-3.5 mr-1 text-emerald-600" aria-hidden />
                Verified
              </Button>
            ) : (
              <Button
                variant="default"
                size="sm"
                className="h-8 text-xs font-medium"
                disabled={busy}
                onClick={() => onVerify(hospital.hid)}
                aria-label={`Verify hospital ${hospital.name}`}
              >
                {busy ? "Verifying…" : "Verify Hospital"}
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
