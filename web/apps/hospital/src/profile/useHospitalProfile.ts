// The administrator's own hospital, loaded once per page through the shared resource hook.

import { useCallback } from "react";

import { useApiResource, useAuth, type Resource } from "@pulseos/ui";

import { api } from "@/api";

import { loadHospitalProfile, type HospitalIdentity } from "./api";

export interface HospitalProfileResource {
  resource: Resource<HospitalIdentity>;
  reload: () => void;
}

export function useHospitalProfile(): HospitalProfileResource {
  const { user } = useAuth();
  const load = useCallback(
    (signal: AbortSignal) =>
      loadHospitalProfile(api, signal, async () => {
        // Claims set during registration only appear in a freshly minted Firebase ID token.
        // ProtectedRoute has already established a signed-in user before this loader runs.
        if (user !== null) {
          await user.getIdToken(true);
        }
      }),
    [user],
  );
  return useApiResource(load);
}
