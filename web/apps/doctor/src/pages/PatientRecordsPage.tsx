// Granted Records: everything one patient's consent currently lets this clinician open.
//
// Reached from Find a Patient, and addressed by the Health ID in the URL — so the page is
// shareable and survives a reload, and no state has to be carried across a navigation.
//
// All state lives in useGrantedRecords; all wording lives in granted/view.ts. This file
// chooses which of the five states to render. Opening a record and downloading its file are
// a later slice: what a clinician may actually read is decided per read at the enforcement
// choke point, never by this listing (ADR-020).

import { ArrowLeft, FolderOpen } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ErrorState } from "@/components/common/ErrorState";
import { Badge, Button, Separator } from "@pulseos/ui";

import { AIAssistantPanel } from "@/components/AIAssistantPanel";
import { EmptyGrantedRecords } from "@/granted/components/EmptyGrantedRecords";
import { GrantedRecordList } from "@/granted/components/GrantedRecordList";
import { GrantedRecordsSkeleton } from "@/granted/components/GrantedRecordsSkeleton";
import { useGrantedRecords } from "@/granted/useGrantedRecords";
import { recordCountLabel } from "@/granted/view";

export interface PatientRecordsPageProps {
  patientId?: string;
}

export function PatientRecordsPage({ patientId: propPatientId }: PatientRecordsPageProps = {}) {
  const { healthId = "" } = useParams<{ healthId: string }>();
  const navigate = useNavigate();
  const records = useGrantedRecords(healthId.length === 0 ? null : healthId);
  const { outcome } = records;
  const patientId = propPatientId ?? healthId;

  const handleSelectCitation = (recordId: string) => {
    const el =
      document.getElementById(`record-${recordId}`) ||
      document.querySelector(`a[href*="/records/${recordId}"]`) ||
      document.querySelector(`[data-record-id="${recordId}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      (el as HTMLElement).focus?.();
    } else {
      navigate(`/records/${encodeURIComponent(recordId)}`, {
        state: { patientHealthId: healthId },
      });
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-2 gap-2">
          <Link to={`/patients?healthId=${encodeURIComponent(healthId)}`}>
            <ArrowLeft className="size-4" aria-hidden />
            Back to patient
          </Link>
        </Button>

        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Granted records</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Everything <span className="font-mono text-[13px]">{healthId}</span> has consented to
            share with you. Access can be withdrawn at any time, and every record you open is
            recorded on the patient's audit trail.
          </p>
        </div>

        {outcome?.kind === "loaded" ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{recordCountLabel(outcome.records.length)}</Badge>
            {outcome.categories.map((category) => (
              <Badge key={category} variant="info">
                {category}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>

      {records.status === "loading" ? (
        <GrantedRecordsSkeleton />
      ) : records.status === "error" || outcome === null ? (
        <ErrorState
          title="Could not load these records."
          message={records.message ?? "Something went wrong."}
          onRetry={records.reload}
        />
      ) : outcome.kind === "no-grant" ? (
        <EmptyGrantedRecords variant="no-grant" patientHealthId={healthId} />
      ) : outcome.kind === "granted-empty" ? (
        <EmptyGrantedRecords
          variant="granted-empty"
          patientHealthId={healthId}
          categories={outcome.categories}
        />
      ) : (
        <>
          <GrantedRecordList records={outcome.records} patientHealthId={healthId} />
          {outcome.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing the {records.pageSize} most recently added records. Older ones are not listed
              yet.
            </p>
          ) : null}
          <p className="text-muted-foreground flex items-start gap-2 text-xs leading-relaxed">
            <FolderOpen className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Select a record to see its details and download the file. Every one you open is recorded
            on the patient's audit trail.
          </p>

          <Separator className="my-8" />

          <AIAssistantPanel
            patientId={patientId}
            patientHealthId={healthId}
            onSelectCitation={handleSelectCitation}
          />
        </>
      )}
    </div>
  );
}
