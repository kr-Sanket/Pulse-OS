// Standing explanation of what the trail guarantees. Uses SectionCard so its header matches
// every other titled panel in the portal.

import { ShieldCheck } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { AUDIT_PRIVACY } from "@/audit/view";

export function AuditInfoCard() {
  return (
    <SectionCard title={AUDIT_PRIVACY.title} icon={ShieldCheck} contentClassName="space-y-3 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{AUDIT_PRIVACY.body}</p>
      <ul className="space-y-2">
        {AUDIT_PRIVACY.points.map((point) => (
          <li key={point} className="text-muted-foreground flex gap-2.5 text-sm leading-relaxed">
            <span className="bg-primary/50 mt-2 size-1.5 shrink-0 rounded-full" aria-hidden />
            {point}
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}
