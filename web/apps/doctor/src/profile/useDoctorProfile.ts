// The clinician's own profile, loaded once per page through the shared resource hook.

import { useCallback } from "react";

import { useApiResource, type Resource } from "@pulseos/ui";

import { api } from "@/api";

import { loadDoctorProfile, type ClinicianIdentity } from "./api";

export interface DoctorProfileResource {
  resource: Resource<ClinicianIdentity>;
  reload: () => void;
}

export function useDoctorProfile(): DoctorProfileResource {
  const load = useCallback((signal: AbortSignal) => loadDoctorProfile(api, signal), []);
  return useApiResource(load);
}
