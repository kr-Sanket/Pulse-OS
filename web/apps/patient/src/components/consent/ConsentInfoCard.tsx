// Standing guidance about what approving a request actually does. Uses SectionCard so its
// header matches every other titled panel in the portal.

import { Info } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { CONSENT_GUIDANCE } from "@/data/consents";

export function ConsentInfoCard() {
  return (
    <SectionCard title={CONSENT_GUIDANCE.title} icon={Info} contentClassName="space-y-3 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{CONSENT_GUIDANCE.body}</p>
      <ul className="space-y-2">
        {CONSENT_GUIDANCE.points.map((point) => (
          <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
            <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
            {point}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
