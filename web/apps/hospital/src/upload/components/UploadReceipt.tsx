// What the administrator sees once the API has created the record.
//
// A receipt rather than a redirect: the one thing worth confirming at a reception desk is
// *which patient* the document was filed against, and the Health ID is not shown anywhere
// else afterwards. The record id is included because it is the only handle anyone has on the
// document — there is no endpoint to edit or delete it.

import { CheckCircle2 } from "lucide-react";

import { Button, Card, CardContent, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/shell/IconChip";
import type { ReceiptView } from "@/upload/view";

export interface UploadReceiptProps {
  receipt: ReceiptView;
  onUploadAnother: () => void;
}

export function UploadReceipt({ receipt, onUploadAnother }: UploadReceiptProps) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
          <IconChip icon={CheckCircle2} tone="solid" size="lg" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <h3 className="text-foreground text-xl font-semibold tracking-tight">Document filed</h3>
            <p className="text-muted-foreground text-sm">
              Filed against{" "}
              <span className="text-foreground font-mono text-[13px] tracking-tight">
                {receipt.patientHealthId}
              </span>
            </p>
          </div>
        </div>

        <Separator />

        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
          <Detail label="Kind of document">{receipt.category}</Detail>
          <Detail label="Date of service">{receipt.dateOfService}</Detail>
          <Detail label="File">
            <span className="break-all">{receipt.filename}</span>
          </Detail>
          <Detail label="Size">{receipt.size}</Detail>
          <Detail label="Uploaded to">{receipt.uploadedTo}</Detail>
          <Detail label="Record ID">
            <span className="font-mono text-[13px] break-all">{receipt.recordId}</span>
          </Detail>
        </dl>

        <Separator />

        <p className="text-muted-foreground text-xs leading-relaxed">
          The record belongs to the patient. Your hospital can read back what it uploaded; anything
          else in their history still needs their consent.
        </p>

        <Button variant="outline" className="w-full justify-center" onClick={onUploadAnother}>
          Upload another document
        </Button>
      </CardContent>
    </Card>
  );
}
