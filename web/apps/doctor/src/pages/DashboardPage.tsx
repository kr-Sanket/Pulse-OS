// Doctor dashboard: who is signed in, where they practise, whether they may act — and the
// one action this slice supports, finding a patient.
//
// Wired to GET /api/v1/doctors/me through useDoctorProfile. The search card hands the
// Health ID to /patients through the URL, so there is exactly one search implementation.

import { IdCard, Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Detail } from "@/components/common/Detail";
import { ErrorState } from "@/components/common/ErrorState";
import { IconChip } from "@/components/shell/IconChip";
import { SectionCard } from "@/components/shell/SectionCard";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { PatientSearchForm } from "@/existence/components/PatientSearchForm";
import { firstNameOf, toIdentityView } from "@/profile/view";
import { useDoctorProfile } from "@/profile/useDoctorProfile";

export function DashboardPage() {
  const { resource, reload } = useDoctorProfile();
  const navigate = useNavigate();
  const identity = resource.status === "ready" ? toIdentityView(resource.data) : null;

  return (
    <div className="space-y-8">
      <div className="space-y-2 pt-1">
        <p className="text-muted-foreground text-sm">Signed in as</p>
        {identity === null ? (
          <Skeleton className="h-9 w-56" />
        ) : (
          <h2 className="text-foreground text-3xl font-semibold tracking-tight">
            Dr {firstNameOf(identity.fullName)}
          </h2>
        )}
      </div>

      {resource.status === "error" ? (
        <ErrorState
          title="Could not load your clinician profile."
          message={resource.message}
          onRetry={reload}
        />
      ) : identity === null ? (
        <IdentitySkeleton />
      ) : (
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
      )}

      <SectionCard
        title="Find a patient"
        icon={Search}
        description="Look up a patient by their Pulse Health ID to see which kinds of record they hold."
        contentClassName="pt-1"
      >
        <PatientSearchForm
          searching={false}
          enabled={identity?.canSearch ?? false}
          onSearch={(healthId) =>
            void navigate(`/patients?healthId=${encodeURIComponent(healthId.trim())}`)
          }
        />
        {identity !== null && !identity.canSearch ? (
          <p role="alert" className="text-destructive pt-3 text-sm leading-relaxed">
            Your clinician profile is {identity.statusLabel.toLowerCase()}. A hospital administrator
            must activate it before you can look up patients.
          </p>
        ) : null}
      </SectionCard>
    </div>
  );
}

function IdentitySkeleton() {
  return (
    <Card className="[--card-spacing:--spacing(6)]" aria-busy role="status" aria-label="Loading">
      <CardContent className="space-y-6">
        <div className="flex items-center gap-5">
          <Skeleton className="size-11 shrink-0 rounded-xl" />
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-6 w-56 max-w-full" />
            <Skeleton className="h-4 w-40" />
          </div>
        </div>
        <Separator />
        <div className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          {["hospital", "specialty", "registration"].map((field) => (
            <div key={field} className="space-y-1.5">
              <Skeleton className="h-2.5 w-24" />
              <Skeleton className="h-4 w-32 max-w-full" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
