// Backend doctor rows → what the roster renders. Pure functions, no React: what a status is
// called, what colour it carries, which action it offers and what that action will actually
// do all live here and are unit-tested. Components stay dumb.
//
// The status vocabulary is deliberately the same one the doctor portal shows the doctor
// themselves ("Active" / "Pending activation" / "Suspended"), so an administrator and a
// clinician looking at the same profile never read two different words for one state.

import { formatInstantDate } from "@pulseos/ui";

import type { Tone } from "@/components/shell/StatusBadge";

import type { Doctor, DoctorStatus } from "./api";

/** Shown when a doctor recorded no specialty — the column is nullable. */
export const NO_SPECIALTY = "Not recorded";

const STATUS_BADGES: Readonly<Record<DoctorStatus, { label: string; tone: Tone }>> = {
  ACTIVE: { label: "Active", tone: "success" },
  PENDING: { label: "Pending activation", tone: "warning" },
  DISABLED: { label: "Suspended", tone: "destructive" },
};

export function statusLabel(status: DoctorStatus): string {
  return STATUS_BADGES[status].label;
}

export function statusTone(status: DoctorStatus): Tone {
  return STATUS_BADGES[status].tone;
}

/** What pressing a doctor's button does — the call, its wording, and its true effect.
 *
 * `effect` is the sentence shown beside the button. Both are written from what the backend
 * actually does: activation is permission to *ask* and never permission to read, and
 * suspension stops reads at the choke point without withdrawing a single grant. */
export interface DoctorAction {
  kind: "activate" | "deactivate";
  label: string;
  busyLabel: string;
  /** Suspending an active doctor is the one action worth making visually distinct. */
  emphasis: "primary" | "quiet";
  effect: string;
}

const ACTIVATE_EFFECT =
  "Lets this doctor search a Pulse Health ID and request access. It grants no record " +
  "access on its own — every read still needs the patient's consent for that category.";

const SUSPEND_EFFECT =
  "Stops this doctor reading anything from their next request onward, even where a patient " +
  "has already granted access. No consent is withdrawn, so reactivating restores it.";

const ACTIONS: Readonly<Record<DoctorStatus, DoctorAction>> = {
  PENDING: {
    kind: "activate",
    label: "Activate",
    busyLabel: "Activating…",
    emphasis: "primary",
    effect: ACTIVATE_EFFECT,
  },
  DISABLED: {
    kind: "activate",
    label: "Reactivate",
    busyLabel: "Reactivating…",
    emphasis: "primary",
    effect: ACTIVATE_EFFECT,
  },
  ACTIVE: {
    kind: "deactivate",
    label: "Suspend",
    busyLabel: "Suspending…",
    emphasis: "quiet",
    effect: SUSPEND_EFFECT,
  },
};

export function actionFor(status: DoctorStatus): DoctorAction {
  return ACTIONS[status];
}

export interface DoctorView {
  id: string;
  fullName: string;
  specialty: string;
  hasSpecialty: boolean;
  registrationNumber: string;
  status: DoctorStatus;
  statusLabel: string;
  statusTone: Tone;
  /** "12 Sep 2026" — when the doctor registered themselves to this hospital. */
  registeredOn: string;
  action: DoctorAction;
}

export function toDoctorView(doctor: Doctor): DoctorView {
  const specialty = doctor.specialty?.trim();
  const hasSpecialty = specialty !== undefined && specialty.length > 0;
  return {
    id: doctor.id,
    fullName: doctor.fullName,
    specialty: hasSpecialty ? specialty : NO_SPECIALTY,
    hasSpecialty,
    registrationNumber: doctor.registrationNumber,
    status: doctor.status,
    statusLabel: statusLabel(doctor.status),
    statusTone: statusTone(doctor.status),
    registeredOn: formatInstantDate(doctor.createdAt),
    action: actionFor(doctor.status),
  };
}

export function toDoctorViews(doctors: readonly Doctor[]): readonly DoctorView[] {
  return doctors.map(toDoctorView);
}

/** Re-file rows whose status this session has already changed.
 *
 * Activating does not refetch: the API answers with the updated row, that status is
 * remembered here, and grouping moves the card into its new section on the next render.
 * Every other card is left exactly as it was — the same approach the patient portal takes
 * when withdrawing a grant. */
export function applyStatusChanges(
  doctors: readonly Doctor[],
  changed: ReadonlyMap<string, DoctorStatus>,
): readonly Doctor[] {
  if (changed.size === 0) {
    return doctors;
  }
  return doctors.map((doctor) => {
    const status = changed.get(doctor.id);
    return status === undefined || status === doctor.status ? doctor : { ...doctor, status };
  });
}

// -- grouping the roster ---------------------------------------------------------------
//
// One section per status, ordered by what an administrator has to act on: whoever is waiting
// on them first, then the roster proper, then the people they have already stood down.

export type DoctorBucket = "pending" | "active" | "suspended";

export interface DoctorBuckets {
  pending: readonly DoctorView[];
  active: readonly DoctorView[];
  suspended: readonly DoctorView[];
}

export const NO_DOCTORS: DoctorBuckets = { pending: [], active: [], suspended: [] };

/** Section order, and the status each one holds. Headings come from `statusLabel`, so a
 * section can never disagree with the badges inside it. */
export const DOCTOR_SECTIONS: readonly { bucket: DoctorBucket; status: DoctorStatus }[] = [
  { bucket: "pending", status: "PENDING" },
  { bucket: "active", status: "ACTIVE" },
  { bucket: "suspended", status: "DISABLED" },
];

const BUCKETS: Readonly<Record<DoctorStatus, DoctorBucket>> = {
  PENDING: "pending",
  ACTIVE: "active",
  DISABLED: "suspended",
};

export function bucketOf(status: DoctorStatus): DoctorBucket {
  return BUCKETS[status];
}

/** Every doctor filed under their section, preserving the API's newest-first order. */
export function groupDoctors(views: readonly DoctorView[]): DoctorBuckets {
  const grouped: Record<DoctorBucket, DoctorView[]> = { pending: [], active: [], suspended: [] };
  for (const view of views) {
    grouped[bucketOf(view.status)].push(view);
  }
  return grouped;
}
