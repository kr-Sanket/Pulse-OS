// Find a patient: a Health ID goes in, the kinds of record they hold come out.
//
// The search itself lives in useRecordExistence; every state the results area can be in
// lives in CategoryResults. This file is layout, plus the one piece of routing behaviour:
// a Health ID arriving in the URL (from the dashboard's search card) runs immediately.

import { FolderOpen, Search } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { SectionCard } from "@/components/shell/SectionCard";
import { Badge, Button } from "@pulseos/ui";

import { CategoryResults } from "@/existence/components/CategoryResults";
import { PatientSearchForm } from "@/existence/components/PatientSearchForm";
import { useRecordExistence } from "@/existence/useRecordExistence";
import { useGrantedRecords } from "@/granted/useGrantedRecords";
import { joinCategories } from "@/granted/view";
import { useDoctorProfile } from "@/profile/useDoctorProfile";
import { toIdentityView } from "@/profile/view";
import { RequestAccessDialog } from "@/requests/components/RequestAccessDialog";
import { useAccessRequest } from "@/requests/useAccessRequest";

export function PatientSearchPage() {
  const [params] = useSearchParams();
  const handedOver = params.get("healthId") ?? "";
  const { outcome, searching, search } = useRecordExistence();
  const { resource } = useDoctorProfile();
  const clinician = resource.status === "ready" ? resource.data : null;
  const identity = clinician?.kind === "registered" ? toIdentityView(clinician.profile) : null;
  const request = useAccessRequest();

  // A new search is a new patient: nothing selected, no half-written draft carried over.
  const startSearch = (healthId: string) => {
    request.reset();
    search(healthId);
  };

  const found = outcome.kind === "found" ? outcome : null;
  const chosenCategories =
    found === null
      ? []
      : found.categories.filter((category) => request.selected.has(category.code));

  // A search that resolved to a real patient — whether or not they hold anything — is also
  // the moment to find out whether this clinician already has access to them. Both outcomes
  // are real patients; only "error" and the pre-search states are not.
  const identified = outcome.kind === "found" || outcome.kind === "none" ? outcome.healthId : null;
  const granted = useGrantedRecords(identified);
  // Shown only where there is genuinely something to view. Never disabled: a button a
  // clinician cannot press teaches them nothing about why.
  const grantedScope =
    granted.outcome === null || granted.outcome.kind === "no-grant"
      ? null
      : granted.outcome.categories;

  // A Health ID in the URL is a search the clinician already started on the dashboard, so
  // it runs once on arrival rather than making them press the button again.
  const alreadyRun = useRef(false);
  useEffect(() => {
    if (handedOver.length > 0 && !alreadyRun.current) {
      alreadyRun.current = true;
      startSearch(handedOver);
    }
    // startSearch is stable for this purpose: it only wraps search and a reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handedOver]);

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Find a patient</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Search by Pulse Health ID. You will see which kinds of record exist — reading any of them
          needs the patient's consent.
        </p>
      </div>

      <SectionCard title="Patient lookup" icon={Search} contentClassName="pt-1">
        <PatientSearchForm
          initialHealthId={handedOver}
          searching={searching}
          enabled={identity === null ? true : identity.canSearch}
          onSearch={startSearch}
        />
      </SectionCard>

      {identified === null || grantedScope === null ? null : (
        <SectionCard
          title="You already have access"
          icon={FolderOpen}
          description={`This patient has approved ${joinCategories(grantedScope)}.`}
          contentClassName="space-y-4 pt-1"
        >
          <div className="flex flex-wrap gap-1.5">
            {grantedScope.map((category) => (
              <Badge key={category} variant="info">
                {category}
              </Badge>
            ))}
          </div>
          <Button asChild className="gap-2">
            <Link to={`/patients/${encodeURIComponent(identified)}/records`}>
              <FolderOpen className="size-4" aria-hidden />
              View Granted Records
            </Link>
          </Button>
        </SectionCard>
      )}

      <CategoryResults
        outcome={outcome}
        selection={{
          selected: request.selected,
          onToggle: request.toggleCategory,
          onClear: request.clearSelection,
          onRequestAccess: request.openDialog,
          canRequest: request.canRequest,
        }}
      />

      {found === null ? null : (
        <RequestAccessDialog
          open={request.dialogOpen}
          onOpenChange={request.setDialogOpen}
          patientHealthId={found.healthId}
          categories={chosenCategories}
          purpose={request.purpose}
          onPurposeChange={request.setPurpose}
          problem={request.problem}
          state={request.state}
          onSubmit={() => request.submit(found.healthId)}
          onFinish={request.finish}
        />
      )}
    </div>
  );
}
