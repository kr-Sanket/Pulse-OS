// The Doctors page's state: the roster, grouped, and one status change at a time per card.
//
// The read goes through the shared useApiResource (loading/error/abort/reload for free); the
// writes are held here because they are per-card. Changing a status does not refetch: the API
// answers with the updated row, that status is remembered, grouping re-files the card on the
// next render, and every other card is left exactly as it was — the same approach the patient
// portal takes when withdrawing a grant.

import { useCallback, useState } from "react";

import { useApiResource } from "@pulseos/ui";

import { api } from "@/api";

import {
  activateDoctor,
  deactivateDoctor,
  listDoctors,
  MAX_PAGE_SIZE,
  type DoctorStatus,
} from "./api";
import {
  applyStatusChanges,
  groupDoctors,
  NO_DOCTORS,
  toDoctorViews,
  type DoctorBuckets,
  type DoctorView,
} from "./view";

export interface DoctorsResource {
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  buckets: DoctorBuckets;
  /** How many doctors the page holds in total — drives the empty state. */
  total: number;
  /** True when the API has more doctors than one page holds. */
  truncated: boolean;
  /** How many a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
  /** Run the action this doctor's status offers (activate, reactivate or suspend). */
  applyAction: (doctor: DoctorView) => void;
  /** Whether a status change is in flight for a doctor. */
  busyOn: (doctorId: string) => boolean;
  /** Why the last status change on a doctor failed, if it did. */
  errorOn: (doctorId: string) => string | null;
}

export function useDoctors(): DoctorsResource {
  const load = useCallback((signal: AbortSignal) => listDoctors(api, signal), []);
  const doctors = useApiResource(load);

  const [changed, setChanged] = useState<ReadonlyMap<string, DoctorStatus>>(new Map());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  const resource = doctors.resource;
  const items = resource.status === "ready" ? resource.data.items : [];
  const buckets =
    resource.status === "ready"
      ? groupDoctors(toDoctorViews(applyStatusChanges(items, changed)))
      : NO_DOCTORS;

  async function run(doctor: DoctorView): Promise<void> {
    setBusy((current) => new Set(current).add(doctor.id));
    setErrors((current) => withoutKey(current, doctor.id));

    const result =
      doctor.action.kind === "activate"
        ? await activateDoctor(api, doctor.id)
        : await deactivateDoctor(api, doctor.id);

    setBusy((current) => withoutSetEntry(current, doctor.id));
    if (result.status === "error") {
      // The card is left exactly as it was. Both calls are idempotent, so pressing the
      // button again simply retries.
      setErrors((current) => ({ ...current, [doctor.id]: result.message }));
      return;
    }
    // The server's own row decides the new status, not an assumption about what the button
    // did — an idempotent call on a row someone else already changed still answers truthfully.
    setChanged((current) => new Map(current).set(doctor.id, result.data.status));
  }

  return {
    status: resource.status === "idle" ? "loading" : resource.status,
    message: resource.status === "error" ? resource.message : null,
    buckets,
    total: items.length,
    truncated: resource.status === "ready" && resource.data.nextCursor !== null,
    pageSize: MAX_PAGE_SIZE,
    reload: doctors.reload,
    applyAction: (doctor) => void run(doctor),
    busyOn: (doctorId) => busy.has(doctorId),
    errorOn: (doctorId) => errors[doctorId] ?? null,
  };
}

/** The record without one key — clearing a card's last error. */
function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([entry]) => entry !== key));
}

function withoutSetEntry(values: ReadonlySet<string>, value: string): Set<string> {
  const next = new Set(values);
  next.delete(value);
  return next;
}
