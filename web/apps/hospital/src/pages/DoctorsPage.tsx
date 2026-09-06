// Doctors: every clinician registered to this hospital, grouped by where they stand, with the
// one action each standing offers.
//
// This is the only surface anywhere for ADR-015 step 3 — a doctor self-registers as PENDING
// and holds no clinical capability until an administrator here activates them.
//
// Two reads: the roster, and the hospital itself. The hospital is not merely a guard — an
// empty roster has to show the HID doctors must register against, and a PENDING hospital
// cannot take registrations at all, so both facts come from the profile.
//
// All state lives in useDoctors; all wording lives in doctors/view.ts. This file chooses
// sections and renders.

import { Navigate } from "react-router-dom";

import { Badge } from "@pulseos/ui";

import { ErrorState } from "@/components/common/ErrorState";
import { DoctorCard } from "@/doctors/components/DoctorCard";
import { DoctorsSkeleton } from "@/doctors/components/DoctorsSkeleton";
import { EmptyDoctors } from "@/doctors/components/EmptyDoctors";
import { useDoctors } from "@/doctors/useDoctors";
import { DOCTOR_SECTIONS, statusLabel, statusTone, type DoctorView } from "@/doctors/view";
import { useHospitalProfile } from "@/profile/useHospitalProfile";
import { toIdentityView } from "@/profile/view";

export function DoctorsPage() {
  const doctors = useDoctors();
  const { resource: profileResource } = useHospitalProfile();
  const outcome = profileResource.status === "ready" ? profileResource.data : null;
  const identity = outcome?.kind === "registered" ? toIdentityView(outcome.profile) : null;

  // An account administering no hospital has no roster — onboard it instead.
  if (outcome?.kind === "unregistered") {
    return <Navigate to="/register" replace />;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">Doctors</h2>
        <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
          Everyone registered to your hospital. Doctors sign up themselves and start pending — a
          pending or suspended doctor can do nothing clinical until you activate them.
        </p>
      </div>

      {doctors.status === "loading" ? (
        <DoctorsSkeleton />
      ) : doctors.status === "error" ? (
        <ErrorState
          title="Could not load your doctors."
          message={doctors.message ?? "Something went wrong."}
          onRetry={doctors.reload}
        />
      ) : doctors.total === 0 ? (
        identity === null ? (
          <DoctorsSkeleton />
        ) : (
          <EmptyDoctors hospitalHid={identity.hospitalHid} canRegister={identity.canOperate} />
        )
      ) : (
        <>
          {DOCTOR_SECTIONS.map((section) => (
            <DoctorSection
              key={section.bucket}
              heading={statusLabel(section.status)}
              tone={statusTone(section.status)}
              doctors={doctors.buckets[section.bucket]}
              busyOn={doctors.busyOn}
              errorOn={doctors.errorOn}
              onAction={doctors.applyAction}
            />
          ))}

          {doctors.truncated ? (
            <p className="text-muted-foreground text-xs">
              Showing your {doctors.pageSize} most recently registered doctors. Older ones are not
              listed yet.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

interface DoctorSectionProps {
  heading: string;
  tone: ReturnType<typeof statusTone>;
  doctors: readonly DoctorView[];
  busyOn: (doctorId: string) => boolean;
  errorOn: (doctorId: string) => string | null;
  onAction: (doctor: DoctorView) => void;
}

/** A section renders only when it holds someone — a hospital with nobody suspended never
 * sees an empty "Suspended" heading. */
function DoctorSection({ heading, tone, doctors, busyOn, errorOn, onAction }: DoctorSectionProps) {
  if (doctors.length === 0) {
    return null;
  }
  const headingId = `${heading.toLowerCase().replace(/\s+/g, "-")}-heading`;
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <div className="flex items-center gap-2.5">
        <h3 id={headingId} className="text-sm font-semibold">
          {heading}
        </h3>
        <Badge variant={tone}>{doctors.length}</Badge>
      </div>
      <div className="space-y-4">
        {doctors.map((doctor) => (
          <DoctorCard
            key={doctor.id}
            doctor={doctor}
            busy={busyOn(doctor.id)}
            error={errorOn(doctor.id)}
            onAction={() => onAction(doctor)}
          />
        ))}
      </div>
    </section>
  );
}
