// The one thing a clinician must be told when their profile is not ACTIVE. Renders nothing
// when there is nothing to say, so callers need no conditional of their own.

import type { DoctorIdentityView } from "@/profile/view";

export interface StatusNoticeProps {
  identity: DoctorIdentityView;
  className?: string;
}

export function StatusNotice({ identity, className }: StatusNoticeProps) {
  if (identity.statusNotice === null) {
    return null;
  }
  return (
    <p role="alert" className={className ?? "text-destructive text-sm leading-relaxed"}>
      {identity.statusNotice}
    </p>
  );
}
