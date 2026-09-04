// Doctor dashboard: who is signed in, where they practise, whether they may act — and the
// one action this slice supports, finding a patient.
//
// Wired to GET /api/v1/doctors/me through useDoctorProfile. The search card hands the
// Health ID to /patients through the URL, so there is exactly one search implementation.

import { Search } from "lucide-react";
import { Navigate, useNavigate } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { Skeleton } from "@/components/ui/skeleton";
import { PatientSearchForm } from "@/existence/components/PatientSearchForm";
import { ClinicianIdentityCard } from "@/profile/components/ClinicianIdentityCard";
import { ClinicianIdentitySkeleton } from "@/profile/components/ClinicianIdentitySkeleton";
import { StatusNotice } from "@/profile/components/StatusNotice";
import { firstNameOf, toIdentityView } from "@/profile/view";
import { useDoctorProfile } from "@/profile/useDoctorProfile";

export function DashboardPage() {
  const { resource, reload } = useDoctorProfile();
  const navigate = useNavigate();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account with no clinician profile has nothing to do here — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

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
        <ClinicianIdentitySkeleton />
      ) : (
        <ClinicianIdentityCard identity={identity} />
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
        {identity === null ? null : (
          <StatusNotice
            identity={identity}
            className="text-destructive pt-3 text-sm leading-relaxed"
          />
        )}
      </SectionCard>
    </div>
  );
}
