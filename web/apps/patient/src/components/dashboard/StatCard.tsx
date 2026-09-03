// A single headline figure: label, value with optional unit, and an optional tone note.
// Matches the v0 vitals treatment — the figure is the focal point, the icon is optional
// and secondary.

import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

import { IconChip } from "./IconChip";
import { StatusBadge, type Tone } from "./StatusBadge";

export interface StatCardProps {
  label: string;
  value: string;
  /** Rendered smaller, on the value's baseline. */
  unit?: string;
  /** Short qualifier shown as a tone badge beneath the value. */
  note?: string;
  tone?: Tone;
  icon?: LucideIcon;
}

export function StatCard({ label, value, unit, note, tone = "neutral", icon }: StatCardProps) {
  return (
    <Card className="[--card-spacing:--spacing(5)]">
      <CardContent className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <p className="text-muted-foreground truncate text-sm">{label}</p>
          {icon === undefined ? null : <IconChip icon={icon} size="sm" />}
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-foreground text-3xl font-semibold tracking-tight tabular-nums">
            {value}
          </span>
          {unit === undefined ? null : (
            <span className="text-muted-foreground text-sm">{unit}</span>
          )}
        </div>
        {note === undefined ? null : <StatusBadge tone={tone}>{note}</StatusBadge>}
      </CardContent>
    </Card>
  );
}
