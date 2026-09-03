// The right-hand summary for the selected record. Hidden below md by the page, which owns
// the responsive decision; this component only renders content.
//
// Download, Share and Print are presentational per spec — the real download already has a
// backend endpoint (POST /records/{id}/download-url) but wiring it is a later slice.

import { Download, Printer, Share2 } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { CATEGORY_STYLE, type MedicalRecord } from "@/data/records";

export interface RecordDetailsPanelProps {
  record: MedicalRecord;
}

/** A labelled fact in the summary list. */
function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-foreground text-sm">{value}</dd>
    </div>
  );
}

export function RecordDetailsPanel({ record }: RecordDetailsPanelProps) {
  const { icon, tone } = CATEGORY_STYLE[record.category];

  return (
    <Card className="sticky top-24">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-3.5">
          <IconChip icon={icon} />
          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="text-foreground text-[15px] font-medium">{record.title}</h2>
            <Badge variant={tone}>{record.category}</Badge>
          </div>
        </div>

        <Separator />

        <dl className="space-y-4">
          <DetailRow label="Hospital" value={record.provider} />
          <DetailRow label="Doctor" value={record.doctor} />
          <DetailRow label="Date of service" value={record.date} />
          <DetailRow label="Description" value={record.description} />
        </dl>

        <Separator />

        <div className="space-y-2">
          <Button variant="default" size="sm" className="w-full justify-center gap-2">
            <Download className="size-4" aria-hidden />
            Download
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" size="sm" className="justify-center gap-2">
              <Share2 className="size-4" aria-hidden />
              Share
            </Button>
            <Button variant="outline" size="sm" className="justify-center gap-2">
              <Printer className="size-4" aria-hidden />
              Print
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
