// Loads the current user's backend-confirmed role from /api/v1/auth/me.
//
// Used by HospitalLayout to decide whether to render the System Admin
// navigation section. Does not expose the admin navigation until
// role verification has succeeded from the backend.

import { useEffect, useState } from "react";

import { api } from "@/api";
import { fetchCurrentUser } from "@/admin/api";
import type { PulseOSClient } from "@pulseos/api-client";

export interface CurrentUserRoleState {
  role: string | null;
  loading: boolean;
  error: string | null;
}

export function useCurrentUserRole(client: PulseOSClient = api): CurrentUserRoleState {
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let mounted = true;

    async function load() {
      setLoading(true);
      setError(null);
      const result = await fetchCurrentUser(client, controller.signal);
      if (!mounted) return;
      if (result.status === "ready") {
        setRole(result.data.role);
      } else {
        setError(result.message);
        setRole(null);
      }
      setLoading(false);
    }

    void load();
    return () => {
      mounted = false;
      controller.abort();
    };
  }, [client]);

  return { role, loading, error };
}
