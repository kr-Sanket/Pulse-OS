// The administrator's own hospital, loaded once per page through the shared resource hook.

import { useCallback } from "react";

import { useApiResource, type Resource } from "@pulseos/ui";

import { api } from "@/api";

import { loadHospitalProfile, type HospitalIdentity } from "./api";

export interface HospitalProfileResource {
  resource: Resource<HospitalIdentity>;
  reload: () => void;
}

export function useHospitalProfile(): HospitalProfileResource {
  const load = useCallback((signal: AbortSignal) => loadHospitalProfile(api, signal), []);
  return useApiResource(load);
}
