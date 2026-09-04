// Find a patient: a Health ID goes in, the kinds of record they hold come out.
//
// The search itself lives in useRecordExistence; every state the results area can be in
// lives in CategoryResults. This file is layout, plus the one piece of routing behaviour:
// a Health ID arriving in the URL (from the dashboard's search card) runs immediately.

import { Search } from "lucide-react";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { SectionCard } from "@/components/shell/SectionCard";
import { CategoryResults } from "@/existence/components/CategoryResults";
import { PatientSearchForm } from "@/existence/components/PatientSearchForm";
import { useRecordExistence } from "@/existence/useRecordExistence";
import { useDoctorProfile } from "@/profile/useDoctorProfile";
import { toIdentityView } from "@/profile/view";

export function PatientSearchPage() {
  const [params] = useSearchParams();
  const handedOver = params.get("healthId") ?? "";
  const { outcome, searching, search } = useRecordExistence();
  const { resource } = useDoctorProfile();
  const identity = resource.status === "ready" ? toIdentityView(resource.data) : null;

  // A Health ID in the URL is a search the clinician already started on the dashboard, so
  // it runs once on arrival rather than making them press the button again.
  const alreadyRun = useRef(false);
  useEffect(() => {
    if (handedOver.length > 0 && !alreadyRun.current) {
      alreadyRun.current = true;
      search(handedOver);
    }
  }, [handedOver, search]);

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
          onSearch={search}
        />
      </SectionCard>

      <CategoryResults outcome={outcome} />
    </div>
  );
}
