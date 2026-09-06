// One record this hospital uploaded, and the way in to it.
//
// Presentational — every string it renders was worded by uploads/view.ts. Unlike the doctor
// portal's granted listing, this one shows the filename: a hospital reading back its own
// upload is disclosed the whole record (ADR-013 layer 2), so nothing is being withheld here
// that the detail page would reveal.
//
// The whole card is a link rather than a card with a button in it: the entire surface is one
// destination, and a real anchor gets keyboard focus, Enter, and open-in-new-tab for free.

import { FileText } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import type { UploadRecordView } from "@/uploads/view";

export interface UploadRecordCardProps {
  record: UploadRecordView;
}

export function UploadRecordCard({ record }: UploadRecordCardProps) {
  return (
    <Link
      to={`/uploads/${encodeURIComponent(record.id)}`}
      className="focus-visible:ring-ring block rounded-xl focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
      aria-label={`Open ${record.categoryName} from ${record.dateOfService}`}
    >
      <Card className="hover:border-primary/30 transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
        <CardContent className="space-y-5">
          <div className="flex items-start gap-4">
            <IconChip icon={FileText} />
            <div className="min-w-0 flex-1">
              <h3 className="text-foreground truncate text-[15px] font-medium tracking-tight">
                {record.categoryName}
              </h3>
              <p className="text-muted-foreground truncate text-sm">{record.fileName}</p>
            </div>
            <StatusBadge tone={record.processingTone}>{record.processingLabel}</StatusBadge>
          </div>

          <Separator />

          <dl className="grid gap-5 sm:grid-cols-3">
            <Detail label="Date of service">{record.dateOfService}</Detail>
            <Detail label="Origin">{record.origin}</Detail>
            <Detail label="Uploaded to PulseOS">{record.uploadedOn}</Detail>
          </dl>
        </CardContent>
      </Card>
    </Link>
  );
}
