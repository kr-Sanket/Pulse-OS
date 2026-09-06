// Hospital dashboard: which hospital this account administers, and whether it may yet
// operate.
//
// Wired to GET /api/v1/hospitals/me through useHospitalProfile. Everything it renders was
// worded by profile/view.ts. The two capabilities named at the bottom are the ones ADR-015
// gates on verification, and neither has a screen yet — so they are described, not linked.

import { Building2 } from "lucide-react";
import { Navigate } from "react-router-dom";

import { Skeleton } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { HospitalIdentityCard } from "@/profile/components/HospitalIdentityCard";
import { HospitalIdentitySkeleton } from "@/profile/components/HospitalIdentitySkeleton";
import { VerificationNotice } from "@/profile/components/VerificationNotice";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { ADMIN_LABEL, firstNameOf, toIdentityView } from "@/profile/view";

export function DashboardPage() {
  const { resource, reload } = useHospitalProfile();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account administering no hospital has nothing to do here — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-2 pt-1">
        <p className="text-muted-foreground text-sm">{ADMIN_LABEL}</p>
        {identity === null ? (
          <Skeleton className="h-9 w-56" />
        ) : (
          <h2 className="text-foreground text-3xl font-semibold tracking-tight">
            {firstNameOf(identity.adminFullName)}
          </h2>
        )}
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

          <SectionCard
            title="What you can do here"
            icon={Building2}
            contentClassName="space-y-3 pt-1"
          >
            <p className="text-muted-foreground text-sm leading-relaxed">
              {identity.canOperate ? CAPABILITIES_INTRO.verified : CAPABILITIES_INTRO.pending}
            </p>
            <ul className="space-y-2">
              {CAPABILITIES.map((capability) => (
                <li
                  key={capability}
                  className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed"
                >
                  <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
                  {capability}
                </li>
              ))}
            </ul>
          </SectionCard>
        </>
      )}
    </div>
  );
}

const CAPABILITIES_INTRO = {
  verified:
    "Your hospital is verified. These are the capabilities it holds; each gets its own " +
    "screen in a later slice.",
  pending:
    "These are the capabilities your hospital will hold once it is verified. Both are " +
    "refused until then.",
} as const;

const CAPABILITIES: readonly string[] = [
  "Doctors register themselves to your hospital, and you activate or suspend them.",
  "You upload a record against a patient's Pulse Health ID, and can read back what your hospital uploaded.",
  "Reading anything your hospital did not upload always needs the patient's consent, and is logged.",
];
