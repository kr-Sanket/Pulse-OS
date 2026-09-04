// The switch that decides which of the two audit views the page shows.
//
// Presentation only, and it says so: the row explains that nothing is removed from the log,
// because a filter over a compliance record is exactly the kind of control a reader is
// entitled to distrust. It reports a change and decides nothing — the filtering itself is
// one pure function in audit/view.ts.
//
// A Radix switch is a button and cannot be wrapped by a <label>, so it is named and
// described by the two lines beside it, the same way the Settings toggles are.

import { Switch } from "@/components/ui/switch";

export interface AuditActivityToggleProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** How many of the patient's own reads are hidden while the switch is off. */
  hiddenCount: number;
}

export function AuditActivityToggle({
  checked,
  onCheckedChange,
  hiddenCount,
}: AuditActivityToggleProps) {
  const labelId = "show-my-activity-label";
  const descriptionId = "show-my-activity-description";

  return (
    <div className="border-border bg-card flex items-start justify-between gap-5 rounded-xl border px-5 py-4">
      <div className="min-w-0 space-y-1">
        <p id={labelId} className="text-foreground text-sm font-medium">
          Show my activity
        </p>
        <p id={descriptionId} className="text-muted-foreground text-sm leading-relaxed">
          {checked
            ? "Showing everything, including the records you opened yourself."
            : hiddenCount === 0
              ? "Your own views and downloads are hidden, so this list shows who else used your records."
              : `${hiddenCount} of your own ${hiddenCount === 1 ? "view or download is" : "views and downloads are"} hidden. Nothing is ever removed from the log.`}
        </p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        className="mt-0.5"
      />
    </div>
  );
}
