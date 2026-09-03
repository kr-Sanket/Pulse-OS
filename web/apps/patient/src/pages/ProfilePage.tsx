// Profile: who the patient is, their Health ID, how to reach them, and how the account is
// secured. Informational only — Edit Profile is visual per spec.
//
// Display name, email and photo come from useAuth(); everything else is mock data in
// src/data/profile.ts. Nothing here calls the API.
//
// NOTE: the previous version of this page was the M0.3 walking skeleton and was the only
// caller of profile/loadProfile.ts (GET /patients/me, registering the patient on first
// login). That bootstrap therefore has no caller now — see .claude/TODO.md.

import { Pencil } from "lucide-react";

import { useAuth } from "@/auth/AuthContext";
import { EmergencyContactCard } from "@/components/profile/EmergencyContactCard";
import { PersonalInfoCard } from "@/components/profile/PersonalInfoCard";
import { ProfileInfoCard } from "@/components/profile/ProfileInfoCard";
import { ProfileSummaryCard } from "@/components/profile/ProfileSummaryCard";
import { SecurityCard } from "@/components/profile/SecurityCard";
import { Button } from "@/components/ui/button";
import { resolveIdentity } from "@/data/profile";

export function ProfilePage() {
  const { user } = useAuth();
  const identity = resolveIdentity(user);

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Profile</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            View your personal information and account details.
          </p>
        </div>
        <Button className="gap-2">
          <Pencil className="size-4" aria-hidden />
          Edit Profile
        </Button>
      </div>

      <ProfileSummaryCard identity={identity} />

      <section aria-labelledby="personal-heading" className="space-y-4">
        <h3 id="personal-heading" className="text-sm font-semibold">
          Personal Information
        </h3>
        <PersonalInfoCard identity={identity} />
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
          <SecurityCard />
        </section>
      </div>

      <ProfileInfoCard />
    </div>
  );
}
