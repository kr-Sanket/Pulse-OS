// Upload a record: file one document against a patient's Pulse Health ID.
//
// The hospital half of POST /api/v1/records. Two reads sit behind it — the category
// vocabulary (inside useRecordUpload) and the hospital itself, which is not merely the
// unregistered guard: ADR-015 refuses an upload from a PENDING hospital with 409, so the form
// is disabled with a reason rather than left to fail after the file has been transferred.
//
// All state lives in useRecordUpload; all wording lives in upload/view.ts.

import { Navigate } from "react-router-dom";

import { formatCalendarDate, formatFileSize } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { HospitalIdentitySkeleton } from "@/profile/components/HospitalIdentitySkeleton";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { toIdentityView } from "@/profile/view";
import { UploadForm } from "@/upload/components/UploadForm";
import { UploadReceipt } from "@/upload/components/UploadReceipt";
import { useRecordUpload } from "@/upload/useRecordUpload";
import { toReceiptView } from "@/upload/view";

export function UploadPage() {
  const upload = useRecordUpload();
  const { resource, reload } = useHospitalProfile();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account administering no hospital cannot upload for anyone — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  const { state } = upload;

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Upload a Record</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          File a document into a patient&rsquo;s PulseOS history. The record belongs to the patient,
          not to your hospital — you will be able to read back what you uploaded, and nothing else
          without their consent.
        </p>
      </div>

      {resource.status === "error" ? (
        <ErrorState
          title="Could not load your hospital."
          message={resource.message}
          onRetry={reload}
        />
      ) : identity === null ? (
        <HospitalIdentitySkeleton />
      ) : state.kind === "uploaded" ? (
        <UploadReceipt
          receipt={toReceiptView(state.record, state.healthId, formatCalendarDate, formatFileSize)}
          onUploadAnother={upload.reset}
        />
      ) : (
        <div className="space-y-4">
          {identity.canOperate ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              {identity.verificationNotice}
            </p>
          )}
          {upload.categoriesUnavailable ? (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              Record categories could not be loaded, so uploads are unavailable right now.
            </p>
          ) : null}

          <UploadForm
            draft={upload.draft}
            problems={upload.problems}
            categories={upload.categories}
            uploading={state.kind === "uploading"}
            enabled={identity.canOperate && !upload.categoriesUnavailable}
            error={state.kind === "error" ? state.message : null}
            onFieldChange={upload.setField}
            onSubmit={upload.submit}
          />
        </div>
      )}
    </div>
  );
}
