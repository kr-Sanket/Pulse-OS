// One granted record: what it is, and its file.
//
// Reached by selecting a card on /patients/:healthId/records, and addressed by the record
// id alone — so the page is shareable and survives a reload. The patient's Health ID rides
// along in navigation state purely so Back can return to the right listing; it is not
// needed to load anything, and the page works without it.
//
// Both calls this page makes cross the enforcement choke point. The listing that led here
// was a filter, not permission: a grant revoked in between refuses the metadata read, and
// the page shows that refusal rather than the record.

import { ArrowLeft } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@pulseos/ui";

import { RecordActions } from "@/record/components/RecordActions";
import { RecordMetadataCard } from "@/record/components/RecordMetadataCard";
import { RecordSkeleton } from "@/record/components/RecordSkeleton";
import { useRecord } from "@/record/useRecord";

/** What the granted listing hands over so Back can name where it came from. */
export interface RecordNavigationState {
  patientHealthId?: string;
}

export function RecordDetailPage() {
  const { recordId = "" } = useParams<{ recordId: string }>();
  const { state } = useLocation() as { state: RecordNavigationState | null };
  const patientHealthId = state?.patientHealthId ?? null;
  const record = useRecord(recordId);

  // Opened from the listing, Back returns to that patient. Opened from a pasted URL there
  // is no patient to return to — the record's own metadata does not name one, deliberately
  // — so Back offers the search instead of guessing.
  const back =
    patientHealthId === null
      ? { to: "/patients", label: "Back to patient search" }
      : {
          to: `/patients/${encodeURIComponent(patientHealthId)}/records`,
          label: "Back to granted records",
        };

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-2 gap-2">
          <Link to={back.to}>
            <ArrowLeft className="size-4" aria-hidden />
            {back.label}
          </Link>
        </Button>

        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">
            {record.record?.fileName ?? "Record"}
          </h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            {patientHealthId === null ? (
              "Shared with you under an active consent grant. Opening and downloading are both recorded on the patient's audit trail."
            ) : (
              <>
                Shared with you by <span className="font-mono text-[13px]">{patientHealthId}</span>.
                Opening and downloading are both recorded on their audit trail.
              </>
            )}
          </p>
        </div>
      </div>

      {record.status === "loading" ? (
        <RecordSkeleton />
      ) : record.status === "error" || record.record === null ? (
        <ErrorState
          title="Could not open this record."
          message={record.message ?? "Something went wrong."}
          onRetry={record.reload}
        />
      ) : (
        <div className="space-y-6">
          <RecordMetadataCard record={record.record} />
          <RecordActions
            fileName={record.record.fileName}
            state={record.download}
            onDownload={record.startDownload}
          />
        </div>
      )}
    </div>
  );
}
