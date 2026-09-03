// Standing note on how this information is held and who can reach it. Uses SectionCard so
// its header matches every other titled panel in the portal.

import { ShieldCheck } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { PROFILE_PRIVACY } from "@/data/profile";

export function ProfileInfoCard() {
  return (
    <SectionCard title={PROFILE_PRIVACY.title} icon={ShieldCheck} contentClassName="space-y-3 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{PROFILE_PRIVACY.body}</p>
      <ul className="space-y-2">
        {PROFILE_PRIVACY.points.map((point) => (
          <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
            <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
            {point}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
