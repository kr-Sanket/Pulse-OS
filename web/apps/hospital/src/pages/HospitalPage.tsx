// My Hospital: the hospital this account administers, in full.
//
// Read-only. There is no PATCH endpoint for a hospital, and nothing on this page pretends
// otherwise — a name or an address is fixed at registration. Verification is likewise not an
// action here: only a PulseOS system administrator can grant it (ADR-015 step 2), so the page
// reports the state and says who changes it rather than offering a button that would 403.
//
// Reuses the dashboard's identity card rather than restating it; the page's own contribution
// is the full detail list and the standing note about what verification means.

import { Building2, ShieldCheck } from "lucide-react";
import { Navigate } from "react-router-dom";

import { Detail } from "@/components/common/Detail";
import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { HospitalIdentityCard } from "@/profile/components/HospitalIdentityCard";
import { HospitalIdentitySkeleton } from "@/profile/components/HospitalIdentitySkeleton";
import { VerificationNotice } from "@/profile/components/VerificationNotice";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { toIdentityView } from "@/profile/view";

export function HospitalPage() {
  const { resource, reload } = useHospitalProfile();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account administering no hospital has nothing to show here — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">My Hospital</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Your hospital record on PulseOS, as doctors and patients see it.
        </p>
      </div>

      {resource.status === "error" ? (
        <ErrorState
          title="Could not load your hospital."
          message={resource.message}
          onRetry={reload}
        />
      ) : identity === null ? (
        <HospitalIdentitySkeleton />
      ) : (
        <>
          <HospitalIdentityCard identity={identity} />

          <VerificationNotice identity={identity} />

          <section aria-labelledby="details-heading" className="space-y-4">
            <h3 id="details-heading" className="text-sm font-semibold">
              Details
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
                  <StatusBadge tone={identity.verificationTone}>
                    {identity.verificationLabel}
                  </StatusBadge>
                </Detail>
                <Detail label="Administrator">{identity.adminFullName}</Detail>
                <Detail label="Registered">{identity.registeredOn}</Detail>
                <Detail label="Address" className="sm:col-span-3">
                  <span className={identity.hasAddress ? undefined : "text-muted-foreground"}>
                    {identity.address}
                  </span>
                </Detail>
              </dl>
            </SectionCard>
          </section>

          <SectionCard
            title="About verification"
            icon={ShieldCheck}
            contentClassName="space-y-3 pt-1"
          >
            <p className="text-muted-foreground text-sm leading-relaxed">
              Only a verified hospital can take doctor registrations or upload records. A PulseOS
              system administrator grants verification; it cannot be requested from this portal.
            </p>
            <ul className="space-y-2">
              {VERIFICATION_POINTS.map((point) => (
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

const VERIFICATION_POINTS: readonly string[] = [
  "Doctors join by registering themselves with your Hospital ID — share it with them.",
  "A doctor starts pending, and holds no clinical capability until you activate them.",
  "Your hospital can always read the records it uploaded; anything else needs the patient's consent.",
];
