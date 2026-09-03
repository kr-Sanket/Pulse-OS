// One preference: its label and explanation, with the switch on the trailing edge.
//
// The row holds no state — every switch position lives on the page, so Reset to Defaults
// can restore them together. The switch is named by its label and described by the line
// under it, since a Radix switch is a button and cannot be wrapped by a <label>.

import { Switch } from "@/components/ui/switch";
import type { PreferenceToggle } from "@/data/settings";

export interface PreferenceToggleRowProps {
  toggle: PreferenceToggle;
  checked: boolean;
  onToggle: (id: string, checked: boolean) => void;
}

export function PreferenceToggleRow({ toggle, checked, onToggle }: PreferenceToggleRowProps) {
  const labelId = `${toggle.id}-label`;
  const descriptionId = `${toggle.id}-description`;

  return (
    <div className="flex items-start justify-between gap-5 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 space-y-1">
        <p id={labelId} className="text-foreground text-sm font-medium">
          {toggle.label}
        </p>
        <p id={descriptionId} className="text-muted-foreground text-sm leading-relaxed">
          {toggle.description}
        </p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={(next) => onToggle(toggle.id, next)}
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        className="mt-0.5"
      />
    </div>
  );
}
