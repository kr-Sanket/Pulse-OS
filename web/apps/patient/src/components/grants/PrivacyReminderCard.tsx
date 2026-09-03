// Standing reminder that access is revocable and time-bound. Uses SectionCard so its header
// matches every other titled panel in the portal.

import { ShieldCheck } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { PRIVACY_REMINDER } from "@/grants/view";

export function PrivacyReminderCard() {
  return (
    <SectionCard
      title={PRIVACY_REMINDER.title}
      icon={ShieldCheck}
      contentClassName="space-y-3 pt-1"
    >
      <p className="text-muted-foreground text-sm leading-relaxed">{PRIVACY_REMINDER.body}</p>
      <ul className="space-y-2">
        {PRIVACY_REMINDER.points.map((point) => (
          <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
            <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
            {point}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
