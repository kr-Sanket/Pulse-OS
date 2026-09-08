// One record, as a card rather than a table row: icon, title, provenance, category and a
// short description, with the action that selects it for the details panel.
//
// Renders the API's own metadata (GET /records). There is no uploading-clinician field on
// that response, so provenance is the uploading hospital — or the patient's own locker.

import { Building2, CalendarDays } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import type { RecordMetadata } from "@/records/api";
import {
  categoryStyle,
  formatCalendarDate,
  HIDDEN_BADGE,
  providerLabel,
  recordDescription,
  recordTitle,
} from "@/records/view";
import { Badge, Button, Card, CardContent, cn } from "@pulseos/ui";

export interface RecordCardProps {
  record: RecordMetadata;
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
  const { icon, tone } = categoryStyle(record.categoryCode);

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
              {recordTitle(record)}
            </h3>
            <div className="flex flex-wrap items-center gap-1.5">
              {/* Information, not a control: the action that changes it lives on the
                  details panel, so a privacy setting is never one stray click away on a
                  page that renders 25 of these. */}
              {record.isHidden ? <Badge variant="warning">{HIDDEN_BADGE}</Badge> : null}
              <Badge variant={tone}>{record.categoryDisplayName}</Badge>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <MetaItem icon={Building2}>{providerLabel(record)}</MetaItem>
            <MetaItem icon={CalendarDays}>{formatCalendarDate(record.dateOfService)}</MetaItem>
          </div>

          <p className="text-muted-foreground text-sm leading-relaxed">
            {recordDescription(record)}
          </p>

          <Button variant="outline" size="sm" onClick={() => onSelect(record.id)}>
            View Details
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
