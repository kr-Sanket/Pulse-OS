// One record the patient's consent has made available, and the way in to it.
//
// Presentational — every string it renders was worded by granted/view.ts. It shows what a
// clinician needs to *choose* a record and nothing that describes the document: no
// filename, no description, no size, no content type, no processing status, and no id. All
// of those are disclosed by opening the record, which authorizes and audits that
// disclosure one record at a time (ADR-020).
//
// The whole card is a link rather than a card with a button in it: the entire surface is
// one destination, and a real anchor gets keyboard focus, Enter, and open-in-new-tab for
// free. The patient's Health ID travels in navigation state purely so the detail page's
// Back link knows which listing to return to.

import { FileText } from "lucide-react";
import { Link } from "react-router-dom";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { GrantedRecordView } from "@/granted/view";

export interface GrantedRecordCardProps {
  record: GrantedRecordView;
  /** Carried into navigation state so the record page can offer a Back link. */
  patientHealthId: string;
}

export function GrantedRecordCard({ record, patientHealthId }: GrantedRecordCardProps) {
  return (
    <Link
      to={`/records/${encodeURIComponent(record.id)}`}
      state={{ patientHealthId }}
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
              <p className="text-muted-foreground truncate text-sm">{record.hospital}</p>
            </div>
            <StatusBadge tone="info">{record.categoryCode}</StatusBadge>
          </div>

          <Separator />

          <dl className="grid gap-5 sm:grid-cols-3">
            <Detail label="Date of service">{record.dateOfService}</Detail>
            <Detail label="Origin">{record.origin}</Detail>
            <Detail label="Added to PulseOS">{record.addedOn}</Detail>
          </dl>
        </CardContent>
      </Card>
    </Link>
  );
}
