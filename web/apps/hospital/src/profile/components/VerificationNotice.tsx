// The one thing an administrator must be told when their hospital is not VERIFIED. Renders
// nothing when there is nothing to say, so callers need no conditional of their own.

import type { HospitalIdentityView } from "@/profile/view";

export interface VerificationNoticeProps {
  identity: HospitalIdentityView;
  className?: string;
}

export function VerificationNotice({ identity, className }: VerificationNoticeProps) {
  if (identity.verificationNotice === null) {
    return null;
  }
  return (
    <p role="alert" className={className ?? "text-destructive text-sm leading-relaxed"}>
      {identity.verificationNotice}
    </p>
  );
}
