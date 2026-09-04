// Account-level actions that touch every record at once, kept apart from the preference
// switches above so a stray tap cannot reach them.
//
// Export Data and Delete Account are presentational per spec — neither calls an endpoint.

import { Database } from "lucide-react";

import { SectionCard } from "@/components/dashboard/SectionCard";
import { Button } from "@/components/ui/button";
import { DATA_CARD, DATA_CONTROLS } from "@/data/settings";
import { cn } from "@pulseos/ui";

export function DataControlsCard() {
  return (
    <SectionCard title={DATA_CARD.title} icon={Database} contentClassName="space-y-3 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{DATA_CARD.description}</p>
      {DATA_CONTROLS.map((control) => {
        const ActionIcon = control.icon;
        return (
          <div
            key={control.id}
            className={cn(
              "flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between",
              control.destructive
                ? "border-destructive/25 bg-destructive/[0.03]"
                : "border-border bg-muted/40",
            )}
          >
            <div className="min-w-0 space-y-1">
              <p className="text-foreground text-sm font-medium">{control.title}</p>
              <p className="text-muted-foreground text-sm leading-relaxed">{control.description}</p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className={cn(
                "justify-center gap-2 sm:w-auto",
                control.destructive ? "text-destructive hover:text-destructive" : undefined,
              )}
            >
              <ActionIcon className="size-4" aria-hidden />
              {control.actionLabel}
            </Button>
          </div>
        );
      })}
    </SectionCard>
  );
}
