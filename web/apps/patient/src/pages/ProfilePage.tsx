// Profile: who the patient is, their Health ID, how to reach them, and how the account is
// secured.
//
// Wired to the backend. The page runs the registration bootstrap through useProfile —
// GET /patients/me, and on a 403 (an authentic Firebase subject with no PulseOS claims)
// POST /patients/register, refresh the ID token, retry — so a first-time patient is issued
// a Health ID by opening this page. That bootstrap had no caller after the M4 redesign
// (.claude/TODO.md); this restores it.
//
// Two sources feed the cards: the profile response owns the health record, the identity
// provider owns email and avatar. Facts neither one holds are shown as missing rather than
// filled in — see profile/view.ts. Edit Profile stays visual: there is no write endpoint.

import { Pencil } from "lucide-react";

import type { PatientProfile } from "@pulseos/api-client";

import { useAuth } from "@pulseos/ui";
import { EmergencyContactCard } from "@/components/profile/EmergencyContactCard";
import { PersonalInfoCard } from "@/components/profile/PersonalInfoCard";
import { ProfileErrorState } from "@/components/profile/ProfileErrorState";
import { ProfileInfoCard } from "@/components/profile/ProfileInfoCard";
import { ProfileSkeleton } from "@/components/profile/ProfileSkeleton";
import { ProfileSummaryCard } from "@/components/profile/ProfileSummaryCard";
import { SecurityCard } from "@/components/profile/SecurityCard";
import { Button } from "@/components/ui/button";
import { useProfile } from "@/profile/useProfile";
import { accountFacts, resolveIdentity, type SignedInIdentity } from "@/profile/view";

export function ProfilePage() {
  const { user } = useAuth();
  const { state, reload } = useProfile();

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Profile</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            View your personal information and account details.
          </p>
        </div>
        <Button className="gap-2" disabled={state.status !== "ready"}>
          <Pencil className="size-4" aria-hidden />
          Edit Profile
        </Button>
      </div>

      {state.status === "loading" ? (
        <ProfileSkeleton />
      ) : state.status === "error" ? (
        <ProfileErrorState message={state.message} onRetry={reload} />
      ) : (
        <ProfileContent profile={state.profile} user={user} />
      )}
    </div>
  );
}

/** The account view itself, once there is a profile to render it from. */
interface ProfileContentProps {
  profile: PatientProfile;
  /** Structurally an AuthUser — email and avatar come from nowhere else. */
  user: SignedInIdentity | null;
}

function ProfileContent({ profile, user }: ProfileContentProps) {
  const identity = resolveIdentity(profile, user);

  return (
    <div className="space-y-10">
      <ProfileSummaryCard identity={identity} account={accountFacts(profile)} />

      <section aria-labelledby="personal-heading" className="space-y-4">
        <h3 id="personal-heading" className="text-sm font-semibold">
          Personal Information
        </h3>
        <PersonalInfoCard profile={profile} identity={identity} />
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <section aria-labelledby="emergency-heading" className="space-y-4">
          <h3 id="emergency-heading" className="text-sm font-semibold">
            Emergency Contact
          </h3>
          <EmergencyContactCard />
        </section>

        <section aria-labelledby="security-heading" className="space-y-4">
          <h3 id="security-heading" className="text-sm font-semibold">
            Account Security
          </h3>
          <SecurityCard identity={identity} />
        </section>
      </div>

      <ProfileInfoCard />
    </div>
  );
}
