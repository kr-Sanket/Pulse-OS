// Standing note on what these preferences do and, more importantly, what they do not do.
// Uses SectionCard so its header matches every other titled panel in the portal.

import { Info } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { SETTINGS_GUIDANCE } from "@/data/settings";

export function SettingsInfoCard() {
  return (
    <SectionCard title={SETTINGS_GUIDANCE.title} icon={Info} contentClassName="space-y-3 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{SETTINGS_GUIDANCE.body}</p>
      <ul className="space-y-2">
        {SETTINGS_GUIDANCE.points.map((point) => (
          <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
            <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
            {point}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
