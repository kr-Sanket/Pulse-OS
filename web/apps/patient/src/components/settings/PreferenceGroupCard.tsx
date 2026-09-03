// One card of related preferences: the shared section header, a line on what the group
// governs, then its switches as a divided list. Every group on the page renders through
// this, so row rhythm and header treatment are defined once.

import { SectionCard } from "@/components/dashboard/SectionCard";
import type { PreferenceGroup, PreferenceState } from "@/data/settings";

import { PreferenceToggleRow } from "./PreferenceToggleRow";

export interface PreferenceGroupCardProps {
  group: PreferenceGroup;
  values: PreferenceState;
  onToggle: (id: string, checked: boolean) => void;
}

export function PreferenceGroupCard({ group, values, onToggle }: PreferenceGroupCardProps) {
  return (
    <SectionCard
      title={group.title}
      icon={group.icon}
      className="h-full"
      contentClassName="space-y-4 pt-1"
    >
      <p className="text-muted-foreground text-sm leading-relaxed">{group.description}</p>
      <div className="divide-border divide-y">
        {group.toggles.map((toggle) => (
          <PreferenceToggleRow
            key={toggle.id}
            toggle={toggle}
            checked={values[toggle.id] ?? toggle.defaultOn}
            onToggle={onToggle}
          />
        ))}
      </div>
    </SectionCard>
  );
}
