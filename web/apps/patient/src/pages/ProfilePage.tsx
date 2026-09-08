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
// filled in — see profile/view.ts.
//
// Edit Profile writes through PATCH /patients/me, which accepts the three fields `patients`
// actually stores: full name, date of birth and gender. Email, Health ID and the account
// facts are read-only because nothing in this API can change them — the Health ID is issued
// once, and the email belongs to the identity provider.

import { Check, Pencil } from "lucide-react";

import { Button, Card, CardContent, useAuth } from "@pulseos/ui";
import { EmergencyContactCard } from "@/components/profile/EmergencyContactCard";
import { PersonalInfoCard } from "@/components/profile/PersonalInfoCard";
import { ProfileErrorState } from "@/components/profile/ProfileErrorState";
import { ProfileInfoCard } from "@/components/profile/ProfileInfoCard";
import { ProfileSkeleton } from "@/components/profile/ProfileSkeleton";
import { ProfileSummaryCard } from "@/components/profile/ProfileSummaryCard";
import { SecurityCard } from "@/components/profile/SecurityCard";
import { PersonalInfoForm } from "@/components/profile/PersonalInfoForm";
import type { PatientProfile } from "@/profile/api";
import { useProfile } from "@/profile/useProfile";
import { useProfileEditor } from "@/profile/useProfileEditor";
import {
  accountFacts,
  resolveIdentity,
  SAVED_CONFIRMATION,
  type SignedInIdentity,
} from "@/profile/view";

export function ProfilePage() {
  const { user } = useAuth();
  const { state, reload, replace } = useProfile();

  return (
    <div className="space-y-10">
      {state.status === "loading" ? (
        <>
          <ProfileHeader />
          <ProfileSkeleton />
        </>
      ) : state.status === "error" ? (
        <>
          <ProfileHeader />
          <ProfileErrorState message={state.message} onRetry={reload} />
        </>
      ) : (
        <ProfileContent profile={state.profile} user={user} onSaved={replace} />
      )}
    </div>
  );
}

/** The heading, and the edit affordance when there is something to edit. */
function ProfileHeader({ action }: { action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Profile</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          View your personal information and account details.
        </p>
      </div>
      {action}
    </div>
  );
}

/** The account view itself, once there is a profile to render it from. */
interface ProfileContentProps {
  profile: PatientProfile;
  /** Structurally an AuthUser — email and avatar come from nowhere else. */
  user: SignedInIdentity | null;
  onSaved: (updated: PatientProfile) => void;
}

function ProfileContent({ profile, user, onSaved }: ProfileContentProps) {
  const identity = resolveIdentity(profile, user);
  const editor = useProfileEditor(profile, onSaved);

  return (
    <div className="space-y-10">
      <ProfileHeader
        action={
          editor.editing ? null : (
            <Button className="gap-2" onClick={editor.begin}>
              <Pencil className="size-4" aria-hidden />
              Edit Profile
            </Button>
          )
        }
      />

      <ProfileSummaryCard identity={identity} account={accountFacts(profile)} />

      <section aria-labelledby="personal-heading" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <h3 id="personal-heading" className="text-sm font-semibold">
            Personal Information
          </h3>
          {editor.saved && !editor.editing ? (
            <span
              role="status"
              className="text-success inline-flex items-center gap-1 text-xs font-medium"
            >
              <Check className="size-3.5" aria-hidden />
              {SAVED_CONFIRMATION}
            </span>
          ) : null}
        </div>
        {editor.editing ? (
          <Card className="[--card-spacing:--spacing(6)]">
            <CardContent>
              <PersonalInfoForm profile={profile} identity={identity} editor={editor} />
            </CardContent>
          </Card>
        ) : (
          <PersonalInfoCard profile={profile} identity={identity} />
        )}
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
