// Hospital onboarding: a signed-in Google account that administers no hospital yet.
//
// Rendered outside HospitalLayout on purpose — an unregistered administrator has no working
// navigation, so a sidebar full of routes that bounce back here would be noise. Once the
// hospital exists the page redirects away and never appears again.
//
// The form replaces itself with the waiting panel on success rather than redirecting: the
// hospital is PENDING, the dashboard would only repeat the same message, and being told what
// happens next is the whole point of the screen.

import { HeartPulse } from "lucide-react";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { Card, CardContent, LoadingScreen } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { HospitalIdentityCard } from "@/profile/components/HospitalIdentityCard";
import { VerificationNotice } from "@/profile/components/VerificationNotice";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { toIdentityView } from "@/profile/view";
import type { HospitalAdminProfile } from "@/register/api";
import { RegistrationForm } from "@/register/components/RegistrationForm";
import { useHospitalRegistration } from "@/register/useHospitalRegistration";
import { REGISTERED } from "@/register/view";

export function RegisterPage() {
  const { resource, reload } = useHospitalProfile();
  const registration = useHospitalRegistration();
  const { state } = registration;

  if (resource.status === "loading" || resource.status === "idle") {
    return <LoadingScreen message="Checking your hospital…" />;
  }
  if (resource.status === "error") {
    return (
      <OnboardingShell>
        <ErrorState
          title="Could not check your hospital."
          message={resource.message}
          onRetry={reload}
        />
      </OnboardingShell>
    );
  }
  // Already an administrator, and not through this form: the portal proper is where they
  // belong. Without this guard, registering a second hospital would be one URL away.
  if (resource.data.kind === "registered" && state.kind !== "registered") {
    return <Navigate to="/" replace />;
  }

  return (
    <OnboardingShell>
      {state.kind === "registered" ? (
        <Registered profile={state.profile} />
      ) : (
        <Card className="[--card-spacing:--spacing(6)]">
          <CardContent className="space-y-6">
            <div className="space-y-1.5">
              <h1 className="text-foreground text-xl font-semibold tracking-tight">
                Register your hospital
              </h1>
              <p className="text-muted-foreground text-sm leading-relaxed">
                A PulseOS system administrator verifies your hospital once these details are
                submitted. Doctors cannot register to it, and no records can be uploaded, until they
                do.
              </p>
            </div>

            <RegistrationForm
              draft={registration.draft}
              problems={registration.problems}
              submitting={state.kind === "submitting"}
              error={state.kind === "error" ? state.message : null}
              onFieldChange={registration.setField}
              onSubmit={registration.submit}
            />
          </CardContent>
        </Card>
      )}
    </OnboardingShell>
  );
}

/** What the administrator sees once the API has accepted the registration. */
function Registered({ profile }: { profile: HospitalAdminProfile }) {
  const identity = toIdentityView(profile);
  return (
    <div className="space-y-6">
      <HospitalIdentityCard identity={identity} />
      <SectionCard title={REGISTERED.title} contentClassName="space-y-3 pt-1">
        <p className="text-muted-foreground text-sm leading-relaxed">{REGISTERED.body}</p>
        <ul className="space-y-2">
          {REGISTERED.points.map((point) => (
            <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
              <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
              {point}
            </li>
          ))}
        </ul>
        <VerificationNotice
          identity={identity}
          className="text-muted-foreground text-sm leading-relaxed"
        />
      </SectionCard>
    </div>
  );
}

/** The onboarding surface: brand, centred column, no navigation. */
function OnboardingShell({ children }: { children: ReactNode }) {
  return (
    <main className="bg-background flex min-h-svh justify-center px-4 py-12">
      <div className="w-full max-w-lg space-y-6">
        <div className="flex items-center gap-2.5">
          <HeartPulse className="text-primary size-6" aria-hidden />
          <div className="min-w-0">
            <span className="block text-[17px] leading-tight font-semibold tracking-tight">
              PulseOS
            </span>
            <span className="text-muted-foreground text-[11px] tracking-wider uppercase">
              Hospital portal
            </span>
          </div>
        </div>
        {children}
      </div>
    </main>
  );
}
