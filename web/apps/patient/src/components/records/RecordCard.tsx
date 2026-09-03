// One record, as a card rather than a table row: icon, title, provenance, category and a
// short description, with the action that selects it for the details panel.

import { Building2, CalendarDays, Stethoscope } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CATEGORY_STYLE, type MedicalRecord } from "@/data/records";
import { cn } from "@/lib/utils";

export interface RecordCardProps {
  record: MedicalRecord;
  /** Highlights the card whose details the panel is showing. */
  selected?: boolean;
  onSelect: (id: string) => void;
}

/** One line of provenance: an icon and its value. */
function MetaItem({ icon: Icon, children }: { icon: typeof Building2; children: React.ReactNode }) {
  return (
    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span className="truncate">{children}</span>
    </span>
  );
}

export function RecordCard({ record, selected = false, onSelect }: RecordCardProps) {
  const { icon, tone } = CATEGORY_STYLE[record.category];

  return (
    <Card
      className={cn(
        "transition-colors duration-150",
        selected ? "ring-primary/30" : "hover:bg-accent/40",
      )}
    >
      <CardContent className="flex gap-4">
        <IconChip icon={icon} />

        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
            <h3 className="text-foreground min-w-0 flex-1 text-[15px] font-medium">
              {record.title}
            </h3>
            <Badge variant={tone}>{record.category}</Badge>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <MetaItem icon={Building2}>{record.provider}</MetaItem>
            <MetaItem icon={Stethoscope}>{record.doctor}</MetaItem>
            <MetaItem icon={CalendarDays}>{record.date}</MetaItem>
          </div>

          <p className="text-muted-foreground text-sm leading-relaxed">{record.description}</p>

          <Button variant="outline" size="sm" onClick={() => onSelect(record.id)}>
            View Details
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
