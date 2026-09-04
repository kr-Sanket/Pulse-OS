// Everything the record endpoint says about one document.
//
// Presentational — every string it renders was worded by record/view.ts, and every field
// comes straight from the response. Nothing is derived: the description row is omitted when
// the uploader recorded none, rather than filled with a placeholder sentence.
//
// This is the first screen in the doctor portal that shows a filename, a size and a content
// type. That is not an oversight in the granted listing: those are withheld there on
// purpose (ADR-020) and disclosed here, where a single authorized read has been audited.

import { FileText } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { SectionCard } from "@/components/shell/SectionCard";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { RecordDetailView } from "@/record/view";

export interface RecordMetadataCardProps {
  record: RecordDetailView;
}

export function RecordMetadataCard({ record }: RecordMetadataCardProps) {
  return (
    <SectionCard title="Record details" icon={FileText} contentClassName="space-y-5 pt-1">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="info">{record.categoryCode}</Badge>
        <span className="text-foreground text-sm font-medium">{record.categoryName}</span>
        <StatusBadge tone={record.processingTone}>{record.processingLabel}</StatusBadge>
      </div>

      <Separator />

      <dl className="grid gap-5 sm:grid-cols-2">
        <Detail label="Date of service">{record.dateOfService}</Detail>
        <Detail label="Uploaded to PulseOS">{record.uploadedOn}</Detail>
        <Detail label="Origin">{record.origin}</Detail>
        <Detail label="Hospital">{record.hospital}</Detail>
        <Detail label="File name">
          <span className="break-all">{record.fileName}</span>
        </Detail>
        <Detail label="File">
          {record.fileType} · {record.fileSize}
        </Detail>
        {record.description === null ? null : (
          <Detail label="Description" className="sm:col-span-2">
            {record.description}
          </Detail>
        )}
      </dl>
    </SectionCard>
  );
}
