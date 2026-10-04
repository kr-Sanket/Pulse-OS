// The clinician's own profile, loaded once per page through the shared resource hook.

import { useCallback } from "react";

import { useApiResource, useAuth, type Resource } from "@pulseos/ui";

import { api } from "@/api";

import { loadDoctorProfile, type ClinicianIdentity } from "./api";

export interface DoctorProfileResource {
  resource: Resource<ClinicianIdentity>;
  reload: () => void;
}

export function useDoctorProfile(): DoctorProfileResource {
  const { user } = useAuth();
  const load = useCallback(
    (signal: AbortSignal) =>
      loadDoctorProfile(api, signal, async () => {
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
