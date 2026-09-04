// My Profile: who this clinician is on PulseOS, and the hospital they act for.
//
// Read-only. There is no PATCH endpoint for a clinician profile, and nothing on this page
// pretends otherwise — a name, a specialty or a hospital is changed by the hospital
// administrator who registered the doctor, not here.
//
// Reuses the dashboard's identity card rather than restating it; the page's own contribution
// is the hospital panel and the standing note about what a status means.

import { Building2, ShieldCheck } from "lucide-react";
import { Navigate } from "react-router-dom";

import { Detail } from "@/components/common/Detail";
import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { ClinicianIdentityCard } from "@/profile/components/ClinicianIdentityCard";
import { ClinicianIdentitySkeleton } from "@/profile/components/ClinicianIdentitySkeleton";
import { StatusNotice } from "@/profile/components/StatusNotice";
import { useDoctorProfile } from "@/profile/useDoctorProfile";
import { toIdentityView } from "@/profile/view";

export function ProfilePage() {
  const { resource, reload } = useDoctorProfile();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account with no clinician profile has nothing to show here — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">My Profile</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Your clinician record on PulseOS. Your hospital administrator maintains these details.
        </p>
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
        <>
          <ClinicianIdentityCard identity={identity} />

          <StatusNotice identity={identity} />

          <section aria-labelledby="hospital-heading" className="space-y-4">
            <h3 id="hospital-heading" className="text-sm font-semibold">
              Hospital
            </h3>
            <SectionCard title={identity.hospitalName} icon={Building2} contentClassName="pt-1">
              <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
                <Detail label="Hospital name">{identity.hospitalName}</Detail>
                <Detail label="Hospital ID">
                  <span className="font-mono text-[13px] tracking-tight">
                    {identity.hospitalHid}
                  </span>
                </Detail>
                <Detail label="Verification">
                  <StatusBadge tone={identity.hospitalVerificationTone}>
                    {identity.hospitalVerificationLabel}
                  </StatusBadge>
                </Detail>
              </dl>
            </SectionCard>
          </section>

          <SectionCard
            title="About your status"
            icon={ShieldCheck}
            contentClassName="space-y-3 pt-1"
          >
            <p className="text-muted-foreground text-sm leading-relaxed">
              Only an active clinician at a verified hospital can look up patients or request access
              to their records.
            </p>
            <ul className="space-y-2">
              {STATUS_POINTS.map((point) => (
                <li
                  key={point}
                  className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed"
                >
                  <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
                  {point}
                </li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

const STATUS_POINTS: readonly string[] = [
  "Your hospital administrator activates, suspends and reactivates your profile.",
  "Searching a patient shows only which kinds of record exist — never their contents.",
  "Reading a record always needs the patient's consent for that category, and is logged.",
];
