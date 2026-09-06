// Uploaded Records: everything this hospital has filed into PulseOS.
//
// GET /records, which for a HOSPITAL_ADMIN is scoped by the server to the records their
// hospital uploaded (ADR-013 layer 2). Nothing here narrows or widens that — there is no
// query to do so, and none is needed.
//
// The listing cannot say *whose* record a row is: `RecordMetadataResponse` carries no
// patient identifier at all. The page says so once, in words, so the absence reads as a
// property of the API rather than a missing column.
//
// All state lives in useUploads; all wording lives in uploads/view.ts.

import { ErrorState } from "@/components/common/ErrorState";
import { EmptyUploads } from "@/uploads/components/EmptyUploads";
import { UploadRecordList } from "@/uploads/components/UploadRecordList";
import { UploadsSkeleton } from "@/uploads/components/UploadsSkeleton";
import { useUploads } from "@/uploads/useUploads";
import { NO_PATIENT_SHOWN, recordCountLabel } from "@/uploads/view";

export function UploadsPage() {
  const uploads = useUploads();

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Uploaded Records</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Every document your hospital has filed into PulseOS, newest first. You can always read
          back what you uploaded; anything else in a patient&rsquo;s history needs their consent.
        </p>
      </div>

      {uploads.status === "loading" ? (
        <UploadsSkeleton />
      ) : uploads.status === "error" || uploads.outcome === null ? (
        <ErrorState
          title="Could not load your uploads."
          message={uploads.message ?? "Something went wrong."}
          onRetry={uploads.reload}
        />
      ) : uploads.outcome.kind === "empty" ? (
        <EmptyUploads />
      ) : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <p className="text-muted-foreground text-sm">
              {recordCountLabel(uploads.outcome.records.length)}
            </p>
            <p className="text-muted-foreground text-xs">{NO_PATIENT_SHOWN}</p>
          </div>

          <UploadRecordList records={uploads.outcome.records} />

          {uploads.outcome.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing your {uploads.pageSize} most recent uploads. Older ones are not listed yet.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
