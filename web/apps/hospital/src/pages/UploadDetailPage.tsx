// One record this hospital uploaded: what it is, and its file.
//
// Addressed by record id alone, so the page is shareable and survives a reload. Both calls
// cross the same authorization the listing did — a record belonging to another hospital
// answers 404 here exactly as it would have been absent from the listing.
//
// The metadata card and the whole detail vocabulary come from @pulseos/ui, so this page and
// the doctor portal's record page describe an identical document identically.

import { ArrowLeft, Download, Loader2, TriangleAlert } from "lucide-react";
import { FileText } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Badge, Button, Separator } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import { ErrorState } from "@/components/common/ErrorState";
import { SectionCard } from "@/components/shell/SectionCard";
import { StatusBadge } from "@/components/shell/StatusBadge";
import { UploadsSkeleton } from "@/uploads/components/UploadsSkeleton";
import { useUpload } from "@/uploads/useUploads";
import { NO_PATIENT_SHOWN, type RecordDetailView } from "@/uploads/view";

export function UploadDetailPage() {
  const { recordId = "" } = useParams<{ recordId: string }>();
  const upload = useUpload(recordId);

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-2 gap-2">
          <Link to="/uploads">
            <ArrowLeft className="size-4" aria-hidden />
            Back to uploaded records
          </Link>
        </Button>

        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">
            {upload.record?.fileName ?? "Record"}
          </h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            {NO_PATIENT_SHOWN}
          </p>
        </div>
      </div>

      {upload.status === "loading" ? (
        <UploadsSkeleton />
      ) : upload.status === "error" || upload.record === null ? (
        <ErrorState
          title="Could not open this record."
          message={upload.message ?? "Something went wrong."}
          onRetry={upload.reload}
        />
      ) : (
        <div className="space-y-6">
          <UploadMetadata record={upload.record} />

          <SectionCard
            title="File"
            icon={Download}
            description="The link is short-lived and issued to you alone. Downloading is recorded on the patient's audit trail."
            contentClassName="space-y-4 pt-1"
          >
            <Button
              className="gap-2"
              disabled={upload.download.kind === "preparing"}
              onClick={upload.startDownload}
            >
              {upload.download.kind === "preparing" ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Download className="size-4" aria-hidden />
              )}
              {upload.download.kind === "preparing" ? "Preparing…" : "Download"}
            </Button>

            <p className="text-muted-foreground text-xs break-all">{upload.record.fileName}</p>

            {upload.download.kind === "failed" ? (
              <p
                role="alert"
                className="text-destructive flex items-start gap-2 text-sm leading-relaxed"
              >
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                {upload.download.message}
              </p>
            ) : null}
          </SectionCard>
        </div>
      )}
    </div>
  );
}

/** Everything the record endpoint says about one document. Presentational — every string was
 * worded by the shared record vocabulary. The description row is omitted when the uploader
 * recorded none, rather than filled with a placeholder sentence. */
function UploadMetadata({ record }: { record: RecordDetailView }) {
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
