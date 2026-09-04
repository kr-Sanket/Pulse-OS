// The account page's signature panel: who is signed in, their Health ID, and the state of
// the account.
//
// Name, Health ID and member-since come from GET /patients/me; email and photo from the
// identity provider, which is the only thing that knows them.

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Detail } from "@/components/common/Detail";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { initialsFor } from "@pulseos/ui";
import type { AccountFacts, ProfileIdentity } from "@/profile/view";

export interface ProfileSummaryCardProps {
  identity: ProfileIdentity;
  account: AccountFacts;
}

export function ProfileSummaryCard({ identity, account }: ProfileSummaryCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <Avatar className="size-20">
            {identity.photoURL === null ? null : <AvatarImage src={identity.photoURL} alt="" />}
            <AvatarFallback className="text-xl font-medium">
              {initialsFor(identity.fullName, identity.email)}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <h3 className="text-foreground text-xl font-semibold tracking-tight">
                {identity.fullName}
              </h3>
              {/* The account's role, which the API establishes by answering at all — not an
                  identity-verification claim, which PulseOS does not make. */}
              <StatusBadge tone="primary">Patient</StatusBadge>
            </div>
            <p className="text-muted-foreground truncate text-sm">{identity.email}</p>
          </div>
        </div>

        <Separator />

        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-3">
          <Detail label="Health ID">
            <span className="font-mono text-[13px] tracking-tight">{account.healthId}</span>
          </Detail>
          <Detail label="Account Status">
            <StatusBadge tone="success">{account.status}</StatusBadge>
          </Detail>
          <Detail label="Member Since">{account.memberSince}</Detail>
        </dl>
      </CardContent>
    </Card>
  );
}
