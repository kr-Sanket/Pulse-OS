// Upload a record: confirm the patient, then file the document.
//
// Two steps, in this order and not negotiable: `POST /records` files a document against a
// Health ID and no endpoint can move or delete it afterwards, so a valid-but-wrong ID used
// to be an unrecoverable mistake. The lookup panel closes that gap — the form below it stays
// disabled until a lookup has succeeded *and* the administrator has confirmed the name.
//
// Three pieces of state, kept apart on purpose: the lookup session (patient-lookup/), the
// document draft (upload/), and the hospital itself. The confirmed patient is passed to
// `submit` rather than stored anywhere, so there is no path that uploads for an
// unconfirmed patient.

import { Navigate } from "react-router-dom";

import { formatCalendarDate, formatFileSize } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { PatientLookupPanel } from "@/patient-lookup/components/PatientLookupPanel";
import { usePatientLookup } from "@/patient-lookup/usePatientLookup";
import { HospitalIdentitySkeleton } from "@/profile/components/HospitalIdentitySkeleton";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { toIdentityView } from "@/profile/view";
import { UploadForm } from "@/upload/components/UploadForm";
import { UploadReceipt } from "@/upload/components/UploadReceipt";
import { useRecordUpload } from "@/upload/useRecordUpload";
import { canUpload, toReceiptView, uploadBlockedReason } from "@/upload/view";

export function UploadPage() {
  const upload = useRecordUpload();
  const lookup = usePatientLookup();
  const { resource, reload } = useHospitalProfile();
  const outcome = resource.status === "ready" ? resource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account administering no hospital cannot upload for anyone — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  const { state } = upload;
  const gate = {
    hospitalCanOperate: identity?.canOperate ?? false,
    categoriesAvailable: !upload.categoriesUnavailable,
    patientConfirmed: lookup.patient !== null,
    draft: upload.draft,
  };

  function startOver(): void {
    upload.reset();
    lookup.reset();
  }

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
          receipt={toReceiptView(state.record, state.patient, formatCalendarDate, formatFileSize)}
          onUploadAnother={startOver}
        />
      ) : (
        <div className="space-y-6">
          {identity.canOperate ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              {identity.verificationNotice}
            </p>
          )}

          <PatientLookupPanel
            session={lookup.session}
            searchable={lookup.searchable}
            enabled={identity.canOperate}
            onHealthIdChange={lookup.setHealthId}
            onFind={lookup.find}
            onConfirmedChange={lookup.setConfirmed}
          />

          <UploadForm
            draft={upload.draft}
            problems={upload.problems}
            categories={upload.categories}
            uploading={state.kind === "uploading"}
            enabled={canUpload(gate)}
            blockedReason={uploadBlockedReason(gate)}
            error={state.kind === "error" ? state.message : null}
            onFieldChange={upload.setField}
            onSubmit={() => {
              // Belt and braces: the button is already closed without a confirmed patient,
              // and `submit` cannot be called without one either.
              if (lookup.patient !== null) {
                upload.submit(lookup.patient);
              }
            }}
          />
        </div>
      )}
    </div>
  );
}
