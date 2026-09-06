// Clinician onboarding: a signed-in Google account that holds no clinician profile yet.
//
// Rendered outside DoctorLayout on purpose — an unregistered clinician has no working
// navigation, so a sidebar full of routes that bounce back here would be noise. Once the
// profile exists the page redirects away and never appears again (requirement: existing
// clinicians must not see it).
//
// The form replaces itself with the waiting panel on success rather than redirecting: the
// profile is PENDING, the dashboard would only repeat the same message, and being told what
// happens next is the whole point of the screen.

import { HeartPulse } from "lucide-react";
import { Navigate } from "react-router-dom";

import { Card, CardContent, LoadingScreen } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { ClinicianIdentityCard } from "@/profile/components/ClinicianIdentityCard";
import { StatusNotice } from "@/profile/components/StatusNotice";
import { useDoctorProfile } from "@/profile/useDoctorProfile";
import { toIdentityView } from "@/profile/view";
import { RegistrationForm } from "@/register/components/RegistrationForm";
import { useDoctorRegistration } from "@/register/useDoctorRegistration";
import { REGISTERED } from "@/register/view";

export function RegisterPage() {
  const { resource, reload } = useDoctorProfile();
  const registration = useDoctorRegistration();
  const { state } = registration;

  if (resource.status === "loading" || resource.status === "idle") {
    return <LoadingScreen message="Checking your clinician profile…" />;
  }
  if (resource.status === "error") {
    return (
      <OnboardingShell>
        <ErrorState
          title="Could not check your clinician profile."
          message={resource.message}
          onRetry={reload}
        />
      </OnboardingShell>
    );
  }
  // Already a clinician, and not through this form: the portal proper is where they belong.
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
                Register as a clinician
              </h1>
              <p className="text-muted-foreground text-sm leading-relaxed">
                Your hospital administrator activates your profile once these details are submitted.
                You cannot look up patients until they do.
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

/** What the clinician sees once the API has accepted the registration. */
function Registered({ profile }: { profile: Parameters<typeof toIdentityView>[0] }) {
  const identity = toIdentityView(profile);
  return (
    <div className="space-y-6">
      <ClinicianIdentityCard identity={identity} />
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
        <StatusNotice
          identity={identity}
          className="text-muted-foreground text-sm leading-relaxed"
        />
      </SectionCard>
    </div>
  );
}

/** The onboarding surface: brand, centred column, no navigation. */
function OnboardingShell({ children }: { children: React.ReactNode }) {
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
              Doctor portal
            </span>
          </div>
        </div>
        {children}
      </div>
    </main>
  );
}
