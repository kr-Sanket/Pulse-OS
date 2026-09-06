// The right-hand summary for the selected record. Hidden below md by the page, which owns
// the responsive decision; this component only renders content.
//
// Its record comes from GET /records/{id} — the read the backend audits — not from the row
// the listing already returned. Download is wired to POST /records/{id}/download-url and
// opens the presigned URL it answers with. Share and Print remain presentational: neither
// has a backend today.

import { Download, Printer, Share2 } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { Badge, Button, Card, CardContent, Separator } from "@pulseos/ui";

import type { RecordMetadata } from "@/records/api";
import {
  categoryStyle,
  formatCalendarDate,
  formatFileSize,
  formatInstantDate,
  providerLabel,
  recordDescription,
  recordTitle,
} from "@/records/view";

export interface RecordDetailsPanelProps {
  record: RecordMetadata;
  onDownload: () => void;
  /** A presigned URL is being requested for this record. */
  downloading: boolean;
  /** Why the last download attempt failed, if it did. */
  downloadError: string | null;
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

export function RecordDetailsPanel({
  record,
  onDownload,
  downloading,
  downloadError,
}: RecordDetailsPanelProps) {
  const { icon, tone } = categoryStyle(record.categoryCode);

  return (
    <Card className="sticky top-24">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-3.5">
          <IconChip icon={icon} />
          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="text-foreground text-[15px] font-medium">{recordTitle(record)}</h2>
            <Badge variant={tone}>{record.categoryDisplayName}</Badge>
          </div>
        </div>

        <Separator />

        <dl className="space-y-4">
          <DetailRow label="Hospital" value={providerLabel(record)} />
          <DetailRow label="Date of service" value={formatCalendarDate(record.dateOfService)} />
          <DetailRow label="Added" value={formatInstantDate(record.createdAt)} />
          <DetailRow label="File" value={record.originalFilename} />
          <DetailRow label="Size" value={formatFileSize(record.sizeBytes)} />
          <DetailRow label="Description" value={recordDescription(record)} />
        </dl>

        <Separator />

        <div className="space-y-2">
          <Button
            variant="default"
            size="sm"
            className="w-full justify-center gap-2"
            onClick={onDownload}
            disabled={downloading}
          >
            <Download className="size-4" aria-hidden />
            {downloading ? "Preparing…" : "Download"}
          </Button>
          {downloadError === null ? null : (
            <p role="alert" className="text-destructive text-xs leading-relaxed">
              {downloadError}
            </p>
          )}
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
